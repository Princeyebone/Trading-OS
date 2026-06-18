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
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

# Ensure the backend/ dir is on sys.path when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.db import get_session, is_db_alive
from engine import data_fetcher, indicators, pattern_detector, claude_analyst, qwen_analyst, broker_executor, telegram_notifier
from engine.rule_engine import evaluate_all as rule_engine_evaluate
from engine.news_guard import is_news_blackout
from engine.outcome_monitor import check_and_close_trades
from engine.trade_manager import manage_open_trades
from engine.market_tape_monitor import detect_tape_events
from engine.scalping_integration import ScalpingIntegration
from app.models.signals import Signal, MarketContext, PatternEvent
from app.models.trades import Trade, TradeJournal, StraddlePair
from app.models.tape import TapeEvent
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
    in_asian  = hour >= 19 or hour < 3  # 7 PM EST to 3 AM EST

    if in_london and in_ny:
        return "OVERLAP"
    elif in_london:
        return "LONDON"
    elif in_ny:
        return "NY"
    elif in_asian:
        return "ASIAN"
        
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
    # 1. Daily max trades (0 means unlimited)
    if config.max_trades_per_day > 0 and len(daily_trades) >= config.max_trades_per_day:
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
        h4_atr = snap.get('h4_atr_percentile', 50.0)
        h1_atr = snap.get('h1_atr_percentile', 50.0)
        logger.info(f"Indicators: H4 alignment={snap.get('h4_alignment')} | ATR pct: H4={h4_atr}% H1={h1_atr}%")

        # ── ATR filter (Regime Selector) ──
        min_atr = config.min_atr_percentile
        h4_align = snap.get('h4_alignment', 'MIXED')
        
        if h4_atr < min_atr and h1_atr < min_atr:
            if h4_align in ["BULLISH", "BEARISH"]:
                logger.info(f"Clean H4 trend detected ({h4_align}) — TREND_OVERRIDE active, TCP permitted")
                snap["volatility_regime"] = "TREND_OVERRIDE"
                snap["regime_constraint"] = (
                    "CONSTRAINT: TREND_OVERRIDE regime (Low volatility but clean H4 trend). "
                    "Only TCP (Trend Continuation Pullback) or NONE (WAIT) may be selected. "
                    "ABE and LSR are forbidden due to low volatility."
                )
            else:
                logger.info(f"ATR (H4 & H1) below {min_atr}th percentile — LOW VOLATILITY REGIME")
                snap["volatility_regime"] = "LOW_VOLATILITY"
                snap["regime_constraint"] = (
                    "CONSTRAINT: LOW VOLATILITY regime detected (Genuine chop). "
                    "Only ABE or NONE (WAIT) may be selected. "
                    "ABE requires ANY ONE of: compression, OR liquidity clustering, OR repeated rejections near same level."
                )
        elif h4_atr < min_atr and h1_atr >= min_atr:
            logger.info(f"ATR H4 < {min_atr}% BUT H1 >= {min_atr}% — SESSION VOLATILITY REGIME (Intraday Spike)")
            snap["volatility_regime"] = "SESSION_VOLATILITY"
            snap["regime_constraint"] = (
                "CONSTRAINT: SESSION VOLATILITY regime (Intraday spike detected despite macro chop). "
                "Evaluate LSR and TCP. "
                "ABE is valid if there is compression OR liquidity clustering."
            )
        else:
            logger.info(f"ATR H4 >= {min_atr}% — NORMAL VOLATILITY REGIME")
            snap["volatility_regime"] = "NORMAL"
            snap["regime_constraint"] = (
                "CONSTRAINT: NORMAL volatility regime. "
                "Evaluate LSR, TCP, and D-FVG. "
                "ABE is only valid if there is compression OR liquidity clustering OR repeated rejections near same level."
            )

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

        # ── Tape Metrics (Raw Order Flow Features) ──
        now = datetime.now(timezone.utc)
        fifteen_mins_ago = now - timedelta(minutes=15)
        tape_events = session.exec(
            select(TapeEvent).where(TapeEvent.created_at >= fifteen_mins_ago).order_by(TapeEvent.created_at.desc())
        ).all()
        
        last_sweep = next((e for e in tape_events if e.event_type == "LIQUIDITY_SWEEP"), None)
        
        tape_metrics = {
            "sweeps_15m": sum(1 for e in tape_events if e.event_type == "LIQUIDITY_SWEEP"),
            "cluster_touches_15m": sum(1 for e in tape_events if e.event_type == "CLUSTER_TOUCH"),
            "rejections_15m": sum(1 for e in tape_events if e.event_type == "REJECTION"),
            "bullish_sweeps": sum(1 for e in tape_events if e.event_type == "LIQUIDITY_SWEEP" and e.direction == "BULLISH"),
            "bearish_sweeps": sum(1 for e in tape_events if e.event_type == "LIQUIDITY_SWEEP" and e.direction == "BEARISH"),
            "last_sweep_age_minutes": int((now - last_sweep.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 60) if last_sweep else None,
            "liquidity_pressure_score": round(len(tape_events) / 15.0, 2)
        }

        # ── Deterministic Rule Engine (runs BEFORE AI — zero API cost) ──
        rule_signal = rule_engine_evaluate(timeframes)
        if rule_signal["verdict"] == "TRADE":
            logger.info(
                f"DETERMINISTIC SIGNAL FIRED | {rule_signal['strategy']} | "
                f"Skipping AI call | direction={rule_signal['direction']} "
                f"entry={rule_signal['entry']} sl={rule_signal['sl']} "
                f"tp1={rule_signal['tp1']} rr={rule_signal['rr']}"
            )
            # Build an analysis-compatible dict so the rest of the pipeline is unchanged
            analysis = {
                "verdict":       rule_signal["verdict"],
                "strategy_name": rule_signal["strategy"],
                "direction":     rule_signal["direction"],
                "confidence":    rule_signal["confidence"],
                "entry":         rule_signal["entry"],
                "stop_loss":     rule_signal["sl"],
                "tp1":           rule_signal["tp1"],
                "tp2":           rule_signal["tp2"],
                "rr_ratio":      rule_signal["rr"],
                "reasoning":     f"Deterministic {rule_signal['strategy']} — {rule_signal['reason']}",
                "warning_flags": [],
                "prompt_version": 0,  # 0 = no prompt used
            }
        else:
            # Rule engine said WAIT — log why and DO NOT fall back to AI (AI is disabled)
            logger.info(
                f"Rule engine WAIT | reason={rule_signal.get('reason')} | "
                f"rules={rule_signal.get('rules_checked')} | AI disabled, skipping."
            )

            # ── AI Disabled ──
            analysis = {
                "verdict": "WAIT",
                "strategy_name": "NONE",
                "direction": None,
                "confidence": 0,
                "reasoning": "Deterministic rule engine returned WAIT. AI analyst is disabled.",
                "warning_flags": [],
                "prompt_version": 0,
            }

        verdict    = analysis.get("verdict", "WAIT")
        direction  = analysis.get("direction")
        confidence = analysis.get("confidence", 0)

        if direction and direction.upper() in ["BULLISH", "BUY", "LONG"]:
            direction = "LONG"
        elif direction and direction.upper() in ["BEARISH", "SELL", "SHORT"]:
            direction = "SHORT"
        elif direction:
            direction = direction.upper()

        logger.info(
            f"Strategy Evaluation | "
            f"Regime={snap.get('volatility_regime')} | "
            f"ATR_Pct={snap.get('atr_percentile')} | "
            f"Selected={analysis.get('strategy_name')} | "
            f"Verdict={verdict}"
        )

        if verdict == "WAIT":
            logger.info(
                f"Rejected Trade | Reasoning={analysis.get('reasoning')} | "
                f"WarningFlags={analysis.get('warning_flags')}"
            )

        source = "DETERMINISTIC" if rule_signal["verdict"] == "TRADE" else config.ai_provider.upper()
        logger.info(f"{source} verdict: {verdict} | Direction: {direction} | Confidence: {confidence}%")

        # ── Log signal ──
        signal = log_signal(
            session, current_session, verdict, direction, confidence, None,
            snap.get("m15_close"), analysis.get("prompt_version", 1), snap, patterns_data
        )

        # ── Execution gate (Confidence removed) ──
        if verdict != "TRADE":
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
        # STRICT RISK MANAGEMENT: Do NOT trust the AI's lot_size hallucination
        lot_size = compute_lot_size(config, sl_pips)

        # ── Execution Gate v1 (Temporal Mismatch Filter) ──
        # Fixes the exact flaw where AI predicts a zone (e.g. 4490) but live price is far away (e.g. 4470).
        live_price = snap.get("m15_close")
        ENTRY_TOLERANCE_POINTS = 3.0  # 30 pips for Gold
        
        # ── ABE STRADDLE OVERRIDE ──
        strategy_name = analysis.get("strategy_name", "")
        is_abe = "ABE" in strategy_name.upper() or "ALPHA BREAKOUT" in strategy_name.upper()

        if is_abe:
            # 0. Check Realtime Monitor Heartbeat (Dead-man switch)
            import os, time
            try:
                if not os.path.exists(".realtime_heartbeat"):
                    raise FileNotFoundError("No heartbeat file")
                with open(".realtime_heartbeat", "r") as f:
                    last_hb = float(f.read().strip())
                if time.time() - last_hb > 180: # 3 minutes
                    raise ValueError("Heartbeat stale")
            except Exception as e:
                logger.error(f"CRITICAL: REALTIME MONITOR OFFLINE ({e}). Blocking Straddle.")
                signal.verdict = "WAIT"
                signal.skip_reason = "REALTIME_MONITOR_OFFLINE"
                session.add(signal)
                session.commit()
                return

            # 1. Enforce Bilateral Liquidity requirement
            liquidity_clusters = patterns_data.get("liquidity", [])
            has_upper = any(c.get("subtype") == "EQUAL_HIGHS" for c in liquidity_clusters)
            has_lower = any(c.get("subtype") == "EQUAL_LOWS" for c in liquidity_clusters)
            
            if not (has_upper and has_lower):
                logger.info("ABE BLOCKED: Missing Bilateral Liquidity structure")
                signal.verdict = "WAIT"
                signal.skip_reason = "MISSING_BILATERAL_LIQUIDITY"
                session.add(signal)
                session.commit()
                return
                
            # 2. Check for active straddles (Singleton Constraint)
            active_straddles = session.exec(select(StraddlePair).where(StraddlePair.status == "ACTIVE")).all()
            if active_straddles:
                logger.info("ABE BLOCKED: An ACTIVE straddle pair already exists")
                signal.verdict = "WAIT"
                signal.skip_reason = "STRADDLE_ALREADY_ACTIVE"
                session.add(signal)
                session.commit()
                return
            
            # 3. Calculate straddle bounds
            upper_bounds = [c["level"] for c in liquidity_clusters if c["subtype"] == "EQUAL_HIGHS"]
            lower_bounds = [c["level"] for c in liquidity_clusters if c["subtype"] == "EQUAL_LOWS"]
            
            buy_stop = max(upper_bounds) + 0.5
            sell_stop = min(lower_bounds) - 0.5
            
            sl_dist = abs(entry - sl)
            if sl_dist == 0: sl_dist = 3.0
            tp1_dist = abs(entry - tp1)
            if tp1_dist == 0: tp1_dist = sl_dist * 2
            
            if DRY_RUN:
                logger.info(f"[DRY RUN] Would straddle: BS={buy_stop}, SS={sell_stop}")
                return
                
            logger.info(f"Executing ABE Straddle: BS={buy_stop}, SS={sell_stop}")
            order_result = broker_executor.place_straddle_orders(
                buy_stop_price=buy_stop,
                sell_stop_price=sell_stop,
                lot_size=lot_size,
                sl_dist=sl_dist,
                tp1_dist=tp1_dist,
                expiration_hours=4
            )
            
            if not order_result["success"]:
                logger.error(f"Straddle failed: {order_result['error']}")
                return
                
            straddle = StraddlePair(
                signal_id=signal.id,
                buy_order_id=order_result["buy_order_id"],
                sell_order_id=order_result["sell_order_id"],
                buy_entry=buy_stop,
                sell_entry=sell_stop,
                status="ACTIVE"
            )
            session.add(straddle)
            session.commit()
            
            telegram_notifier.notify_trade_executed(
                direction="STRADDLE",
                entry=live_price,
                stop_loss=buy_stop - sl_dist,
                tp1=buy_stop + tp1_dist,
                tp2=0,
                lot_size=lot_size,
                confidence=confidence,
                order_id=f"BS:{order_result['buy_order_id']}|SS:{order_result['sell_order_id']}",
                reasoning=f"ABE Bilateral Straddle Placed. BuyStop={buy_stop}, SellStop={sell_stop}",
            )
            return

        # Regular execution tolerance check
        price_distance = abs(live_price - entry)
        if price_distance > ENTRY_TOLERANCE_POINTS:
            logger.info(
                f"ENTRY BLOCKED | Price too far from zone | "
                f"live={live_price}, entry={entry}, diff={price_distance:.2f}, tol={ENTRY_TOLERANCE_POINTS}"
            )
            signal.verdict = "WAIT"
            signal.skip_reason = "PRICE_TOO_FAR"
            session.add(signal)
            session.commit()
            return

        # ── Demo execution ──
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would execute: {direction} {lot_size} lots @ {entry} SL={sl} TP1={tp1}")
            return

        logger.info(f"Executing: {direction} {lot_size} lots @ ~{entry} (Step-Trailing TP)")
        order_result = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=0.0,  # CRITICAL: TP is 0.0 for Ratcheting TP system
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

# ─── Scalping Job ──────────────────────────────────────────────────────────────
_scalping_integration = None

def run_scalping_cycle():
    """Runs every minute to check for scalping signals on M5 data."""
    global DRY_RUN, _scalping_integration
    
    if _scalping_integration is None:
        _scalping_integration = ScalpingIntegration()
        
    logger.info("Scalping cycle starting...")
        
    session = get_session()
    try:
        config = session.exec(select(EngineConfig).order_by(EngineConfig.id.desc())).first()
        if not config:
            logger.warning("No EngineConfig found. Scalping skipped.")
            return
            
        if not config.is_active:
            return
            
        executed = _scalping_integration.check_and_execute(config)
        
        if executed:
            for sig in executed:
                logger.info(f"Scalp Executed: {sig['direction']} {sig['type']} @ {sig['price']}")
                telegram_notifier.notify_info("Scalping Engine", f"Executed {sig['direction']} {sig['type']} @ {sig['price']}")
                
    except Exception as e:
        logger.exception(f"Scalping cycle error: {e}")
    finally:
        session.close()


# ─── Entry point ────────────────────────────────────────────────────────────────
def start_background_scheduler():
    global DRY_RUN
    DRY_RUN = False  # Production backend implies live execution, unless toggled elsewhere
    
    scheduler = BackgroundScheduler(timezone="America/New_York")
    # Fire exactly at minute 0, 15, 30, 45 (candle close)
    scheduler.add_job(run_engine_cycle, "cron", minute="0,15,30,45", id="engine_cycle")
    scheduler.add_job(check_and_close_trades, "cron", minute="*/5", id="outcome_monitor")
    scheduler.add_job(manage_open_trades, "interval", seconds=5, id="trade_manager")
    scheduler.add_job(detect_tape_events, "cron", minute="*", id="tape_monitor")
    scheduler.add_job(run_scalping_cycle, "cron", minute="*", id="scalping_cycle")
    
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

    # Also monitor open trades every 5 minutes and manage trades every 1 min
    scheduler = BlockingScheduler(timezone="America/New_York")
    scheduler.add_job(run_engine_cycle, "cron", minute="0,15,30,45", id="engine_cycle")
    scheduler.add_job(check_and_close_trades, "cron", minute="*/5", id="outcome_monitor")
    scheduler.add_job(manage_open_trades, "interval", seconds=5, id="trade_manager")
    scheduler.add_job(detect_tape_events, "cron", minute="*", id="tape_monitor")
    scheduler.add_job(run_scalping_cycle, "cron", minute="*", id="scalping_cycle")

    logger.info("🚀 Engine scheduler started — running every 15 minutes")
    logger.info("   Press Ctrl+C to stop")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Engine stopped by user")


if __name__ == "__main__":
    main()
