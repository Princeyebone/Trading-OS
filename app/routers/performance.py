"""
Performance analytics router.
GET /api/performance/summary
GET /api/performance/by-pattern
GET /api/performance/by-session
GET /api/performance/by-hour
GET /api/performance/equity-curve
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func
from app.database import get_session
from app.models.trades import Trade, TradeOutcome
from app.models.signals import Signal, MarketContext

router = APIRouter(prefix="/api/performance", tags=["performance"])


def _compute_win_rate(wins: int, total: int) -> float:
    return round((wins / total) * 100, 1) if total > 0 else 0.0


@router.get("/summary")
def performance_summary(session: Session = Depends(get_session)):
    """Overall performance metrics — used by the Dashboard."""
    trades = session.exec(select(Trade)).all()
    outcomes = session.exec(select(TradeOutcome)).all()

    total = len(trades)
    wins = sum(1 for t in trades if t.status == "WIN")
    losses = sum(1 for t in trades if t.status == "LOSS")
    breakevens = sum(1 for t in trades if t.status == "BE")
    open_trades = sum(1 for t in trades if t.status == "OPEN")

    r_values = [o.r_achieved for o in outcomes if o.r_achieved is not None]
    avg_r = round(sum(r_values) / len(r_values), 2) if r_values else 0.0

    pnl_values = [o.pnl_dollars for o in outcomes if o.pnl_dollars is not None]
    total_pnl = round(sum(pnl_values), 2) if pnl_values else 0.0

    # Equity curve — cumulative P&L by date
    equity_curve = []
    cumulative = 0.0
    sorted_outcomes = sorted(outcomes, key=lambda o: o.closed_at)
    for o in sorted_outcomes:
        if o.pnl_dollars is not None:
            cumulative += o.pnl_dollars
            equity_curve.append({
                "date": o.closed_at.isoformat(),
                "cumulative_pnl": round(cumulative, 2),
                "trade_pnl": round(o.pnl_dollars, 2),
            })

    signals = session.exec(select(Signal)).all()
    total_signals = len(signals)
    trade_signals = sum(1 for s in signals if s.verdict == "TRADE")

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "open_trades": open_trades,
        "win_rate": _compute_win_rate(wins, total - open_trades),
        "avg_r_achieved": avg_r,
        "total_pnl_dollars": total_pnl,
        "total_signals": total_signals,
        "trade_signals": trade_signals,
        "equity_curve": equity_curve,
    }


@router.get("/by-pattern")
def performance_by_pattern(session: Session = Depends(get_session)):
    """Win rate grouped by pattern type."""
    from app.models.signals import PatternEvent
    trades = session.exec(select(Trade)).all()
    trade_map = {t.signal_id: t for t in trades if t.signal_id}

    patterns = session.exec(select(PatternEvent)).all()
    pattern_stats: dict = {}

    for p in patterns:
        t = trade_map.get(p.signal_id)
        if not t:
            continue
        key = p.pattern_type
        if key not in pattern_stats:
            pattern_stats[key] = {"wins": 0, "losses": 0, "total": 0}
        if t.status == "WIN":
            pattern_stats[key]["wins"] += 1
        elif t.status == "LOSS":
            pattern_stats[key]["losses"] += 1
        if t.status in ("WIN", "LOSS", "BE"):
            pattern_stats[key]["total"] += 1

    result = []
    for pattern, stats in pattern_stats.items():
        result.append({
            "pattern": pattern,
            **stats,
            "win_rate": _compute_win_rate(stats["wins"], stats["total"]),
        })
    return sorted(result, key=lambda x: x["win_rate"], reverse=True)


@router.get("/by-session")
def performance_by_session(session: Session = Depends(get_session)):
    """Win rate grouped by trading session (LONDON, NY, OVERLAP)."""
    trades = session.exec(select(Trade)).all()
    signals = {s.id: s for s in session.exec(select(Signal)).all()}

    session_stats: dict = {}
    for t in trades:
        if t.status not in ("WIN", "LOSS", "BE"):
            continue
        sig = signals.get(t.signal_id)
        key = sig.session if sig else "UNKNOWN"
        if key not in session_stats:
            session_stats[key] = {"wins": 0, "losses": 0, "total": 0}
        if t.status == "WIN":
            session_stats[key]["wins"] += 1
        elif t.status == "LOSS":
            session_stats[key]["losses"] += 1
        session_stats[key]["total"] += 1

    return [
        {"session": k, **v, "win_rate": _compute_win_rate(v["wins"], v["total"])}
        for k, v in session_stats.items()
    ]


@router.get("/by-hour")
def performance_by_hour(session: Session = Depends(get_session)):
    """Win rate grouped by hour of day (0–23) based on trade open time."""
    trades = session.exec(select(Trade)).all()

    hour_stats: dict = {h: {"wins": 0, "losses": 0, "total": 0} for h in range(24)}
    for t in trades:
        if t.status not in ("WIN", "LOSS", "BE"):
            continue
        hour = t.opened_at.hour
        if t.status == "WIN":
            hour_stats[hour]["wins"] += 1
        elif t.status == "LOSS":
            hour_stats[hour]["losses"] += 1
        hour_stats[hour]["total"] += 1

    return [
        {"hour": h, **s, "win_rate": _compute_win_rate(s["wins"], s["total"])}
        for h, s in hour_stats.items()
        if s["total"] > 0
    ]
