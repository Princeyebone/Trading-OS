"""
engine/scheduler.py — Main APScheduler orchestration loop.

Runs every 15 minutes (configurable) during London + NY sessions.
Full pipeline: pre-flight → data → indicators → patterns → Claude → gate → execute → log.

Usage:
    python -m engine.scheduler            # run live
    python -m engine.scheduler --dry-run  # log only, no execution
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

# Ensure the backend/ dir is on sys.path when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.db import get_session, is_db_alive
from engine import data_fetcher, indicators, pattern_detector, claude_analyst, qwen_analyst, broker_executor, telegram_notifier
from engine.news_guard import is_news_blackout
from engine.outcome_monitor import check_and_close_trades
from app.models.signals import Signal, MarketContext, PatternEvent
from app.models.trades import Trade, TradeJournal
from app.models.config import EngineConfig

# Force-set the log level for all "engine" loggers and configure direct stdout output
engine_logger = logging.getLogger("engine")
engine_logger.setLevel(logging.INFO)
if not engine_logger.handlers:
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s"))
    engine_logger.addHandler(sh)
    engine_logger.propagate = False

logger = logging.getLogger("engine.scheduler")

EST = ZoneInfo("America/New_York")
DRY_RUN = False


# ─── Session detection ─────────────────────────────────────────────────────────
def get_current_session(config: EngineConfig) -> str | None:
    """
    Returns "LONDON", "NY", "OVERLAP", or None if outside session windows.
    All hours in EST.
    """
    now_est = datetime.now(EST)
    hour = now_est.hour

    in_london = config.london_start_hour <= hour < config.london_end_hour
    in_ny     = config.ny_start_hour <= hour < config.ny_end_hour

    if in_london and in_ny:
        return "OVERLAP"
    elif in_london:
        return "LONDON"
    elif in_ny:
        return "NY"
    return None


# ─── Pre-flight checks ─────────────────────────────────────────────────────────
def run_preflight(session: Session, config: EngineConfig) -> tuple[bool, str]:
    """
    Run all pre-flight checks. Returns (ok, skip_reason).
    """
    # 1. DB alive
    if not is_db_alive():
        return False, "DB_UNREACHABLE"

    # 2. Session window
    current_session = get_current_session(config)
    if current_session is None:
        return False, "OUTSIDE_SESSION"

    # 3. Daily trade limit
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_trades = session.exec(
        select(Trade).where(Trade.opened_at >= today_start).where(Trade.status != "CANCELLED")
    ).all()
    if len(daily_trades) >= config.max_trades_per_day:
        return False, f"DAILY_LIMIT_REACHED ({len(daily_trades)}/{config.max_trades_per_day})"

    # 4. Max open trades
    open_trades = session.exec(select(Trade).where(Trade.status == "OPEN")).all()
    if len(open_trades) >= config.max_open_trades:
        return False, f"MAX_OPEN_TRADES ({len(open_trades)})"

    # 5. Consecutive loss pause
    recent_closed = session.exec(
        select(Trade).where(Trade.status.in_(["WIN", "LOSS", "BE"]))
        .order_by(Trade.closed_at.desc()).limit(config.consecutive_loss_pause)
    ).all()
    if len(recent_closed) == config.consecutive_loss_pause:
        if all(t.status == "LOSS" for t in recent_closed):
            return False, f"CONSECUTIVE_LOSS_PAUSE ({config.consecutive_loss_pause} losses)"

    # 6. News blackout — check ForexFactory for high-impact events within ±N minutes
    in_blackout, event_label = is_news_blackout(config.news_blackout_minutes)
    if in_blackout:
        return False, f"NEWS_BLACKOUT ({event_label})"

    return True, current_session


# ─── Position sizing ────────────────────────────────────────────────────────────
def compute_lot_size(config: EngineConfig, stop_loss_pips: float) -> float:
    """
    Lot Size = (Balance × Risk%) / (SL pips × pip_value_per_micro_lot)
    Gold: 1 pip = $0.10 per micro lot (0.01 lots)
    """
    risk_dollars = config.account_balance_equiv * (config.max_risk_percent / 100)
    pip_value_per_micro = 1.0   # $1 per pip per 0.10 lot
    if stop_loss_pips <= 0:
        return 0.01
    raw_lots = risk_dollars / (stop_loss_pips * pip_value_per_micro)
    # Round down to nearest 0.01
    return max(0.01, round(raw_lots - (raw_lots % 0.01), 2))


# ─── Log signal to DB ──────────────────────────────────────────────────────────
def log_signal(
    session: Session,
    session_name: str,
    verdict: str,
    direction,
    confidence,
    skip_reason,
    price,
    prompt_version,
    indicator_snapshot: dict,
    patterns_data: dict,
) -> Signal:
    signal = Signal(
        timeframe="M15",
        session=session_name,
        verdict=verdict,
        direction=direction,
        confidence=confidence,
        skip_reason=skip_reason,
        price_at_signal=price,
        prompt_version=prompt_version,
    )
    session.add(signal)
    session.flush()  # get signal.id

    # Market context
    mc = MarketContext(
        signal_id=signal.id,
        session=session_name,
        atr=indicator_snapshot.get("m15_atr"),
        atr_percentile=indicator_snapshot.get("atr_percentile"),
        rsi_m15=indicator_snapshot.get("m15_rsi"),
        rsi_h1=indicator_snapshot.get("h1_rsi"),
        macd_hist_h1=indicator_snapshot.get("h1_macd_hist"),
        h4_ema20=indicator_snapshot.get("h4_ema_20"),
        h4_ema50=indicator_snapshot.get("h4_ema_50"),
        h4_ema200=indicator_snapshot.get("h4_ema_200"),
        h4_alignment=indicator_snapshot.get("h4_alignment"),
        h1_ema20=indicator_snapshot.get("h1_ema_20"),
        stoch_m15=indicator_snapshot.get("m15_stoch_k"),
        volume_ratio=indicator_snapshot.get("m15_vol_ratio"),
    )
    session.add(mc)

    # Pattern events
    for p in patterns_data.get("patterns", []):
        session.add(PatternEvent(
            signal_id=signal.id,
            pattern_type=p.get("type", "UNKNOWN"),
            timeframe=p.get("timeframe", "H1"),
            direction=p.get("direction"),
            confidence=p.get("confidence"),
            price_level=p.get("level") or p.get("mid"),
            details=str(p),
        ))

    session.commit()
    return signal


# ─── Main engine cycle ─────────────────────────────────────────────────────────
def run_engine_cycle():
    """Single engine cycle — complete detect-analyse-execute-log pipeline."""
    logger.info("=" * 60)
    logger.info("Engine cycle starting...")
    session = get_session()

    try:
        # ── Load config ──
        config = session.exec(
            select(EngineConfig).where(EngineConfig.is_active == True)
        ).first()
        if not config:
            config = EngineConfig()

        # ── Pre-flight ──
        ok, result = run_preflight(session, config)
        if not ok:
            logger.info(f"Pre-flight SKIP: {result}")
            log_signal(
                session=session,
                session_name="OFF_HOURS" if "SESSION" in result else "PREFLIGHT",
                verdict="WAIT",
                direction=None,
                confidence=None,
                skip_reason=result,
                price=None,
                prompt_version=1,
                indicator_snapshot={},
                patterns_data={}
            )
            return

        current_session = result  # the session name
        logger.info(f"Pre-flight OK | Session: {current_session}")

        # ── Data layer ──
        try:
            timeframes, is_stale = data_fetcher.fetch_all_timeframes()
            logger.info("OHLCV data fetched OK")
        except RuntimeError as e:
            logger.warning(f"Data fetch skip: {e}")
            return

        # ── Indicators ──
        timeframes = indicators.compute_all_indicators(timeframes)
        snap = indicators.extract_indicator_snapshot(timeframes)
        logger.info(f"Indicators: H4 alignment={snap.get('h4_alignment')} | ATR pct={snap.get('atr_percentile')}")

        # ── ATR filter ──
        if snap.get("atr_percentile", 100) < config.min_atr_percentile:
            logger.info(f"ATR below {config.min_atr_percentile}th percentile — SKIP (ranging)")
            log_signal(session, current_session, "WAIT", None, None,
                       f"ATR_BELOW_THRESHOLD ({snap['atr_percentile']})", snap.get("m15_close"),
                       1, snap, {"patterns": [], "liquidity": []})
            return

        # ── Pattern detection ──
        patterns_data = pattern_detector.detect_all_patterns(timeframes)
        logger.info(f"Patterns detected: {len(patterns_data['patterns'])} | Liquidity: {len(patterns_data['liquidity'])}")

        # ── Stale Data Check ──
        if is_stale:
            logger.info("Data is stale (market closed/lagging) — logging context and SKIPPING analysis")
            log_signal(session, current_session, "WAIT", None, None,
                       "STALE_DATA", snap.get("m15_close"),
                       1, snap, patterns_data)
            return

        # ── Account state ──
        open_count = len(session.exec(select(Trade).where(Trade.status == "OPEN")).all())
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_count = len(session.exec(select(Trade).where(Trade.opened_at >= today_start)).all())
        account_state = {
            "balance": config.account_balance_equiv,
            "open_trades": open_count,
            "daily_trades": daily_count,
        }

        # ── AI Analysis ──
        logger.info(f"Calling {config.ai_provider.upper()} API...")
        if config.ai_provider.lower() == "qwen":
            analysis = qwen_analyst.analyse_market(snap, patterns_data, current_session, account_state)
        else:
            analysis = claude_analyst.analyse_market(snap, patterns_data, current_session, account_state)
        verdict    = analysis.get("verdict", "WAIT")
        direction  = analysis.get("direction")
        confidence = analysis.get("confidence", 0)
        logger.info(f"{config.ai_provider.upper()} verdict: {verdict} | Direction: {direction} | Confidence: {confidence}%")

        # ── Log signal ──
        signal = log_signal(
            session, current_session, verdict, direction, confidence, None,
            snap.get("m15_close"), analysis.get("prompt_version", 1), snap, patterns_data
        )

        # ── Confidence gate ──
        if verdict != "TRADE" or (confidence or 0) < config.confidence_threshold:
            logger.info(f"WAIT — confidence {confidence}% < threshold {config.confidence_threshold}%")
            return

        # ── H4 trend alignment gate ──
        h4_align = snap.get("h4_alignment", "MIXED")
        if direction == "LONG" and h4_align == "BEARISH":
            logger.info("WAIT — LONG blocked by bearish H4 alignment")
            signal.verdict = "WAIT"
            signal.skip_reason = "H4_TREND_MISMATCH"
            session.add(signal)
            session.commit()
            return
        if direction == "SHORT" and h4_align == "BULLISH":
            logger.info("WAIT — SHORT blocked by bullish H4 alignment")
            signal.verdict = "WAIT"
            signal.skip_reason = "H4_TREND_MISMATCH"
            session.add(signal)
            session.commit()
            return

        # ── Position sizing ──
        entry = analysis.get("entry") or snap.get("m15_close")
        sl    = analysis.get("stop_loss")
        tp1   = analysis.get("tp1")
        tp2   = analysis.get("tp2")

        if not all([entry, sl, tp1]):
            logger.warning("Missing entry/SL/TP from Claude — WAIT")
            return

        sl_pips = abs(entry - sl) * 10
        lot_size = analysis.get("lot_size") or compute_lot_size(config, sl_pips)

        # ── Demo execution ──
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would execute: {direction} {lot_size} lots @ {entry} SL={sl} TP1={tp1}")
            return

        logger.info(f"Executing: {direction} {lot_size} lots @ ~{entry}")
        order_result = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp1,
        )

        if not order_result["success"]:
            logger.error(f"Order failed: {order_result['error']}")
            return

        # ── Log trade ──
        trade = Trade(
            signal_id=signal.id,
            direction=direction,
            planned_entry=entry,
            actual_entry=order_result["actual_entry"],
            slippage_pips=order_result["slippage_pips"],
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            lot_size=lot_size,
            planned_rr=analysis.get("rr_ratio"),
            broker_order_id=order_result["order_id"],
            status="OPEN",
        )
        session.add(trade)
        session.flush()

        # Pre-trade journal entry
        session.add(TradeJournal(
            trade_id=trade.id,
            pre_trade_analysis=analysis.get("reasoning", ""),
        ))
        session.commit()

        # ── Telegram ──
        telegram_notifier.notify_trade_executed(
            direction=direction,
            entry=order_result["actual_entry"],
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            lot_size=lot_size,
            confidence=confidence,
            order_id=order_result["order_id"],
            reasoning=analysis.get("reasoning", ""),
        )

        logger.info(f"Trade logged: ID={trade.id} | Order={order_result['order_id']}")

    except Exception as e:
        logger.exception(f"Engine cycle error: {e}")
        telegram_notifier.notify_error("Scheduler", str(e))
    finally:
        session.close()


# ─── Entry point ────────────────────────────────────────────────────────────────
def start_background_scheduler():
    global DRY_RUN
    DRY_RUN = False  # Production backend implies live execution, unless toggled elsewhere
    
    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(run_engine_cycle, "interval", minutes=15, id="engine_cycle")
    scheduler.add_job(check_and_close_trades, "interval", minutes=5, id="outcome_monitor")
    
    logger.info("🚀 Background Engine scheduler started inside FastAPI")
    scheduler.start()
    return scheduler

def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(description="Trading OS Engine Scheduler")
    parser.add_argument("--dry-run", action="store_true", help="Log only — no trades executed")
    parser.add_argument("--once", action="store_true", help="Run one cycle immediately and exit")
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    if DRY_RUN:
        logger.info("🔵 DRY RUN MODE — no trades will be executed")

    if args.once:
        run_engine_cycle()
        return

    # Also monitor open trades every 5 minutes
    scheduler = BlockingScheduler(timezone="America/New_York")
    scheduler.add_job(run_engine_cycle, "interval", minutes=15, id="engine_cycle")
    scheduler.add_job(check_and_close_trades, "interval", minutes=5, id="outcome_monitor")

    logger.info("🚀 Engine scheduler started — running every 15 minutes")
    logger.info("   Press Ctrl+C to stop")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Engine stopped by user")


if __name__ == "__main__":
    main()
