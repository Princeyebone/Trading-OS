"""
optimizer/data_aggregator.py — Pull weekly trading data from PostgreSQL for the Optimizer.

Computes statistical summaries that the Claude optimizer uses to generate suggestions.
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from sqlmodel import Session, select

from engine.db import get_session
from app.models.trades import Trade, TradeOutcome, TradeJournal
from app.models.signals import Signal, MarketContext, PatternEvent

logger = logging.getLogger(__name__)


def _win_rate(wins: int, total: int) -> float:
    return round((wins / total) * 100, 1) if total > 0 else 0.0


def aggregate_weekly_stats(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> dict:
    """
    Pull all relevant data for the optimizer period.
    Default: last 7 days.
    Returns a structured dict ready to pass to the Claude optimizer prompt.
    """
    if period_end is None:
        period_end = date.today()
    if period_start is None:
        period_start = period_end - timedelta(days=7)

    start_dt = datetime(period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc)
    end_dt   = datetime(period_end.year, period_end.month, period_end.day, 23, 59, 59, tzinfo=timezone.utc)

    session = get_session()
    try:
        # All signals in period
        signals = session.exec(
            select(Signal).where(Signal.created_at >= start_dt).where(Signal.created_at <= end_dt)
        ).all()

        # All trades in period
        trades = session.exec(
            select(Trade).where(Trade.opened_at >= start_dt).where(Trade.opened_at <= end_dt)
        ).all()

        # Outcomes for those trades
        trade_ids = [t.id for t in trades]
        outcomes = session.exec(
            select(TradeOutcome).where(TradeOutcome.trade_id.in_(trade_ids))
        ) .all() if trade_ids else []

        # Journal entries
        journals = session.exec(
            select(TradeJournal).where(TradeJournal.trade_id.in_(trade_ids))
        ).all() if trade_ids else []

        # Market context for signals
        signal_ids = [s.id for s in signals]
        contexts = session.exec(
            select(MarketContext).where(MarketContext.signal_id.in_(signal_ids))
        ).all() if signal_ids else []

        # Pattern events
        patterns = session.exec(
            select(PatternEvent).where(PatternEvent.signal_id.in_(signal_ids))
        ).all() if signal_ids else []

    finally:
        session.close()

    # ── Basic stats ──
    closed_trades = [t for t in trades if t.status in ("WIN", "LOSS", "BE")]
    wins   = sum(1 for t in closed_trades if t.status == "WIN")
    losses = sum(1 for t in closed_trades if t.status == "LOSS")

    r_values = [o.r_achieved for o in outcomes if o.r_achieved is not None]
    avg_r = round(sum(r_values) / len(r_values), 2) if r_values else 0.0

    # ── By session ──
    session_map: dict = {}
    signal_lookup = {s.id: s for s in signals}
    for t in closed_trades:
        sig = signal_lookup.get(t.signal_id)
        sess = sig.session if sig else "UNKNOWN"
        if sess not in session_map:
            session_map[sess] = {"wins": 0, "losses": 0, "total": 0}
        if t.status == "WIN":
            session_map[sess]["wins"] += 1
        elif t.status == "LOSS":
            session_map[sess]["losses"] += 1
        session_map[sess]["total"] += 1

    by_session = {
        k: {**v, "win_rate": _win_rate(v["wins"], v["total"])}
        for k, v in session_map.items()
    }

    # ── By pattern ──
    pattern_map: dict = {}
    trade_by_signal = {}
    for t in closed_trades:
        if t.signal_id:
            trade_by_signal[t.signal_id] = t
    for p in patterns:
        t = trade_by_signal.get(p.signal_id)
        if not t:
            continue
        key = p.pattern_type
        if key not in pattern_map:
            pattern_map[key] = {"wins": 0, "losses": 0, "total": 0}
        if t.status == "WIN":
            pattern_map[key]["wins"] += 1
        elif t.status == "LOSS":
            pattern_map[key]["losses"] += 1
        pattern_map[key]["total"] += 1

    by_pattern = {
        k: {**v, "win_rate": _win_rate(v["wins"], v["total"])}
        for k, v in pattern_map.items()
    }

    # ── Confidence calibration ──
    confidence_buckets: dict = {}
    for t in closed_trades:
        sig = signal_lookup.get(t.signal_id)
        if sig and sig.confidence:
            bucket = (sig.confidence // 5) * 5
            if bucket not in confidence_buckets:
                confidence_buckets[bucket] = {"wins": 0, "total": 0}
            if t.status == "WIN":
                confidence_buckets[bucket]["wins"] += 1
            confidence_buckets[bucket]["total"] += 1

    confidence_calibration = {
        f"{k}-{k+4}%": {**v, "win_rate": _win_rate(v["wins"], v["total"])}
        for k, v in sorted(confidence_buckets.items())
    }

    # ── RSI at entry for winners vs losers ──
    rsi_winners = []
    rsi_losers  = []
    for t in closed_trades:
        sig = signal_lookup.get(t.signal_id)
        if not sig:
            continue
        ctx = next((c for c in contexts if c.signal_id == sig.id), None)
        if ctx and ctx.rsi_m15:
            if t.status == "WIN":
                rsi_winners.append(ctx.rsi_m15)
            elif t.status == "LOSS":
                rsi_losers.append(ctx.rsi_m15)

    avg_rsi_winners = round(sum(rsi_winners) / len(rsi_winners), 1) if rsi_winners else None
    avg_rsi_losers  = round(sum(rsi_losers) / len(rsi_losers), 1) if rsi_losers else None

    # ── TP achievement ──
    tp1_reached = sum(1 for o in outcomes if o.exit_reason == "TP1_HIT")
    tp2_reached = sum(1 for o in outcomes if o.exit_reason == "TP2_HIT")

    # ── Journal insight snippets ──
    improvement_hints = [j.improvement_hint for j in journals if j.improvement_hint]
    wrong_patterns   = [j.what_went_wrong for j in journals if j.what_went_wrong and j.what_went_wrong != "N/A"]

    return {
        "period_start": str(period_start),
        "period_end":   str(period_end),
        "total_signals": len(signals),
        "trade_signals": sum(1 for s in signals if s.verdict == "TRADE"),
        "wait_signals":  sum(1 for s in signals if s.verdict == "WAIT"),
        "total_trades":  len(closed_trades),
        "wins":          wins,
        "losses":        losses,
        "win_rate":      _win_rate(wins, len(closed_trades)),
        "avg_r_achieved": avg_r,
        "by_session":    by_session,
        "by_pattern":    by_pattern,
        "confidence_calibration": confidence_calibration,
        "rsi_analysis": {
            "avg_rsi_at_entry_winners": avg_rsi_winners,
            "avg_rsi_at_entry_losers":  avg_rsi_losers,
            "rsi_differential":         round(avg_rsi_losers - avg_rsi_winners, 1)
                                        if avg_rsi_winners and avg_rsi_losers else None,
        },
        "tp_achievement": {
            "tp1_hit": tp1_reached,
            "tp2_hit": tp2_reached,
            "tp1_rate": _win_rate(tp1_reached, wins) if wins else 0,
            "tp2_rate": _win_rate(tp2_reached, wins) if wins else 0,
        },
        "journal_hints": improvement_hints[:5],
        "common_failure_patterns": wrong_patterns[:5],
    }
