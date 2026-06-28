"""
engine/outcome_monitor.py — Background job that polls open trades and records closes.

Runs every 5 minutes via APScheduler. When a trade's SL or TP is hit,
it records the outcome, generates an AI post-trade journal entry, and
sends a Telegram notification.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Session, select

from engine.db import get_session
from engine.broker_executor import get_open_positions
from engine import telegram_notifier
from app.models.trades import Trade, TradeOutcome, TradeJournal

logger = logging.getLogger(__name__)


def _compute_result(actual_profit: float) -> str:
    """Determine WIN, LOSS, or BE based on actual PnL."""
    if actual_profit > 0:
        return "WIN"
    elif actual_profit < 0:
        return "LOSS"
    return "BE"


def _compute_pnl(trade: Trade, exit_price: float, actual_profit: float) -> tuple[float, float]:
    """Returns (pnl_pips, pnl_dollars)."""
    if trade.direction == "LONG":
        pips = (exit_price - trade.actual_entry) * 10 if trade.actual_entry else 0
    else:
        pips = (trade.actual_entry - exit_price) * 10 if trade.actual_entry else 0
    
    return round(pips, 1), round(actual_profit, 2)


def _compute_r_achieved(trade: Trade, exit_price: float) -> float:
    """Compute R multiple achieved."""
    if not trade.actual_entry:
        return 0.0
    risk = abs(trade.actual_entry - trade.stop_loss)
    if risk == 0:
        return 0.0
    if trade.direction == "LONG":
        reward = exit_price - trade.actual_entry
    else:
        reward = trade.actual_entry - exit_price
    return round(reward / risk, 2)


def _generate_post_trade_journal(trade: Trade, outcome: TradeOutcome) -> dict:
    """
    Generate AI post-trade journal entry via Claude.
    Simplified version — full prompt construction would include original signal data.
    """
    result_text = "winning" if outcome.r_achieved and outcome.r_achieved > 0 else "losing"
    return {
        "post_trade_analysis": f"Trade closed with {outcome.exit_reason}. R achieved: {outcome.r_achieved}R.",
        "what_went_right": "Trade followed the system rules." if result_text == "winning" else "Entry was at a valid technical level.",
        "what_went_wrong": "N/A" if result_text == "winning" else "Market did not follow through on the setup.",
        "improvement_hint": "Continue monitoring for similar setups.",
        "market_conditions": f"Exit at {outcome.exit_price}",
    }


def check_and_close_trades():
    """
    Main monitoring function — called every 5 minutes.
    Checks MT5 open positions vs DB open trades. Records any closes.
    """
    session = get_session()
    try:
        # Get all open trades from DB
        open_trades = session.exec(
            select(Trade).where(Trade.status == "OPEN")
        ).all()

        if not open_trades:
            return

        # Get current open positions from broker
        broker_positions = get_open_positions()
        open_tickets = {str(p["ticket"]) for p in broker_positions}

        for trade in open_trades:
            # If trade no longer in broker positions → it closed
            if trade.broker_order_id and trade.broker_order_id not in open_tickets:
                # Find the position that closed — get exit price from broker history
                # For now use the last known price (simplified)
                exit_price, actual_profit = _get_exit_data_from_broker(trade)
                if exit_price is None:
                    logger.warning(f"Cannot determine exit price for trade {trade.id}")
                    continue

                _record_close(session, trade, exit_price, actual_profit)

    except Exception as e:
        logger.error(f"check_and_close_trades error: {e}")
        telegram_notifier.notify_error("OutcomeMonitor", str(e))
    finally:
        session.close()


def _get_exit_data_from_broker(trade: Trade) -> tuple[Optional[float], float]:
    """
    Retrieve the actual close price and exact broker profit from MT5 history.
    """
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return None, 0.0
            
        deals = mt5.history_deals_get(position=int(trade.broker_order_id or 0))
        if deals:
            exit_price = None
            total_profit = 0.0
            for d in deals:
                if d.entry == 1:  # DEAL_ENTRY_OUT
                    exit_price = float(d.price)
                    total_profit += float(d.profit)
            if exit_price is not None:
                return exit_price, total_profit
    except Exception as e:
        logger.error(f"Error getting exit data for trade {trade.id}: {e}")
    return None, 0.0


def _record_close(session: Session, trade: Trade, exit_price: float, actual_profit: float):
    """Record trade close — outcome, journal, notifications."""
    result = _compute_result(actual_profit)
    pnl_pips, pnl_dollars = _compute_pnl(trade, exit_price, actual_profit)
    r_achieved = _compute_r_achieved(trade, exit_price)

    # Determine exit reason
    if trade.direction == "LONG":
        if exit_price >= trade.take_profit_1:
            exit_reason = "TP1_HIT"
        elif trade.take_profit_2 and exit_price >= trade.take_profit_2:
            exit_reason = "TP2_HIT"
        else:
            exit_reason = "SL_HIT"
    else:
        if exit_price <= trade.take_profit_1:
            exit_reason = "TP1_HIT"
        elif trade.take_profit_2 and exit_price <= trade.take_profit_2:
            exit_reason = "TP2_HIT"
        else:
            exit_reason = "SL_HIT"

    if trade.opened_at.tzinfo is None:
        # Postgres SQLAlchemy strips timezone and converts to local time if column is naive
        closed_at = datetime.now()
        duration_mins = int((closed_at - trade.opened_at).total_seconds() / 60)
        closed_at_utc = datetime.now(timezone.utc)
    else:
        closed_at = datetime.now(timezone.utc)
        duration_mins = int((closed_at - trade.opened_at).total_seconds() / 60)
        closed_at_utc = closed_at

    # Update trade record
    trade.status = result
    trade.closed_at = closed_at_utc
    session.add(trade)

    # Create outcome record
    outcome = TradeOutcome(
        trade_id=trade.id,
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl_pips=pnl_pips,
        pnl_dollars=pnl_dollars,
        r_achieved=r_achieved,
        duration_mins=duration_mins,
        closed_at=closed_at_utc,
    )
    session.add(outcome)

    # Generate journal entry
    journal_data = _generate_post_trade_journal(trade, outcome)
    existing_journal = session.exec(
        select(TradeJournal).where(TradeJournal.trade_id == trade.id)
    ).first()

    if existing_journal:
        for k, v in journal_data.items():
            setattr(existing_journal, k, v)
        session.add(existing_journal)
    else:
        session.add(TradeJournal(trade_id=trade.id, **journal_data))

    session.commit()

    # Telegram notification
    telegram_notifier.notify_trade_outcome(
        direction=trade.direction,
        entry=trade.actual_entry or trade.planned_entry,
        exit_price=exit_price,
        result=result,
        pnl_dollars=pnl_dollars,
        pnl_pips=pnl_pips,
        r_achieved=r_achieved,
        exit_reason=exit_reason,
        duration_mins=duration_mins,
        ticket=trade.broker_order_id,
    )

    logger.info(f"Trade {trade.id} closed: {result} | R={r_achieved} | P&L=${pnl_dollars}")
