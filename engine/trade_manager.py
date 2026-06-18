"""
engine/trade_manager.py — Trade Lifecycle Management Module

Runs periodically (e.g. every 1 minute) to manage open trades:
1. Partial close at TP1.
2. Move Stop Loss to Break-Even.
3. Trail remaining position to lock in runners.
"""
import logging
import MetaTrader5 as mt5
from sqlmodel import select
from datetime import datetime, timezone, timedelta

from engine.db import get_session
from app.models.trades import Trade, TradeOutcome, StraddlePair
from engine import broker_executor, telegram_notifier

logger = logging.getLogger("engine.trade_manager")

TP1_THRESHOLD_PIPS = 10.0   # First harvest: 10 pips (1.0 Gold point)
TP1_CLOSE_PERCENT   = 25.0  # Lock 25% at TP1, leave 75% running
TRAIL_DISTANCE_PIPS = 30.0  # Tightened trail — runner follows within 30 pips
BUFFER_PIPS = 5.0

import pandas as pd

def manage_open_trades():
    """
    Check all OPEN trades in the database against live market prices.
    Executes partial closures, BE moves, and trailing stops.
    """
    session = get_session()
    try:
        # Use FOR UPDATE to lock rows and prevent scheduler conflicts
        open_trades = session.exec(select(Trade).where(Trade.status == "OPEN").with_for_update()).all()
        if not open_trades:
            return

        # Initialize MT5 to fetch live prices
        if not broker_executor._init_mt5():
            logger.error("Trade Manager: MT5 not initialized, skipping cycle.")
            return
            
        tick = mt5.symbol_info_tick(broker_executor.SYMBOL)
        if not tick:
            logger.error(f"Trade Manager: Could not get tick for {broker_executor.SYMBOL}")
            return
            
        live_bid = tick.bid
        live_ask = tick.ask
        
        for trade in open_trades:
            if not trade.broker_order_id:
                continue
                
            entry = trade.actual_entry or trade.planned_entry
            ticket = int(trade.broker_order_id)
            
            # Fetch MT5 position to ensure it's still open
            mt5_pos = mt5.positions_get(ticket=ticket)
            if not mt5_pos:
                continue
                
            # Determine Step Size based on Signal
            step_size_pips = 30.0  # Default for TCP (3.0 points)
            if trade.signal_id:
                from app.models.signals import Signal
                sig = session.get(Signal, trade.signal_id)
                if sig and sig.session == "SCALP":
                    step_size_pips = 15.0  # Default for Scalp (1.5 points)
                
            # Calculate live profit in pips
            if trade.direction == "LONG":
                profit_pips = (live_bid - entry) * 10
            else:
                profit_pips = (entry - live_ask) * 10
                
            trade_type = "SCALP" if step_size_pips == 15.0 else "TCP"
            logger.info(f"📊 [Step TP Monitor] Trade #{trade.id} ({trade_type}): Current Profit = {profit_pips/10.0:.2f} pts | Locked = {trade.locked_profit_pips/10.0:.2f} pts")
                
            # Update highest profit
            dirty = False
            if profit_pips > trade.highest_profit_pips:
                trade.highest_profit_pips = profit_pips
                dirty = True
                
            # --- Ratcheting TP Logic ---
            # 1. Lock in profits if we crossed a new step threshold
            if profit_pips >= trade.locked_profit_pips + step_size_pips:
                new_lock = (profit_pips // step_size_pips) * step_size_pips
                if new_lock > trade.locked_profit_pips:
                    trade.locked_profit_pips = new_lock
                    dirty = True
                    logger.info(f"🔒 LOCKED {trade.locked_profit_pips/10.0:.1f} pts profit for trade #{trade.id}")
                    telegram_notifier.notify_info("Step TP", f"🔒 Trade #{trade.id} LOCKED +{trade.locked_profit_pips/10.0:.1f} pts")
                    
                    # Optionally move SL natively to protect MT5 state if server dies
                    # (Break-even + locked profit - buffer)
                    protect_pips = trade.locked_profit_pips - (step_size_pips * 0.5)
                    if protect_pips > 0:
                        new_sl = entry + (protect_pips / 10.0) if trade.direction == "LONG" else entry - (protect_pips / 10.0)
                        broker_executor.modify_position_sl(ticket, new_sl)
            
            # 2. Check for Reversal (Close Condition)
            if trade.locked_profit_pips > 0 and profit_pips < trade.locked_profit_pips:
                logger.info(f"🎯 STEP TP TRIGGERED for trade #{trade.id}! Reversal detected. Closing at locked {trade.locked_profit_pips/10.0:.1f} pts.")
                success = broker_executor.close_position(ticket)
                if success:
                    trade.status = "WIN"
                    dirty = True
                    telegram_notifier.notify_success("Step TP Hit", f"🎯 Trade #{trade.id} closed at +{trade.locked_profit_pips/10.0:.1f} pts!")
            
            if dirty:
                session.add(trade)
                session.commit()
                
    except Exception as e:
        logger.exception(f"Trade Manager loop error: {e}")
    finally:
        session.close()

def monitor_straddles():
    """
    Monitor active ABE pending stop orders (straddles).
    """
    session = get_session()
    try:
        active_straddles = session.exec(select(StraddlePair).where(StraddlePair.status == "ACTIVE")).all()
        if not active_straddles:
            return

        for straddle in active_straddles:
            buy_ticket = straddle.buy_order_id
            sell_ticket = straddle.sell_order_id
            
            # Check MT5 for status
            status = broker_executor.check_straddle_status(buy_ticket, sell_ticket)
            
            buy_filled = status["buy_filled"]
            sell_filled = status["sell_filled"]
            buy_expired = status["buy_expired"]
            sell_expired = status["sell_expired"]

            if buy_filled and sell_filled:
                # Whipsaw scenario: both filled before we could cancel
                logger.error(f"STRADDLE WHIPSAW: Both sides filled for straddle #{straddle.id}")
                straddle.status = "ERROR"
                session.add(straddle)
                session.commit()
                continue

            if buy_filled:
                logger.info(f"Straddle #{straddle.id} BUY_STOP filled. Cancelling SELL_STOP #{sell_ticket}...")
                broker_executor.cancel_order(sell_ticket)
                if broker_executor.verify_cancellation(sell_ticket):
                    straddle.cancellation_confirmed = True
                    straddle.status = "FILLED"
                else:
                    telegram_notifier.notify_error("Trade Manager", f"CRITICAL: STRADDLE LEG CANCELLATION UNCONFIRMED for ticket {sell_ticket}")
                    straddle.status = "ERROR"
                    # HALT NEW TRADE PLACEMENT - handled by relying on Singleton constraint (it remains ACTIVE or ERROR so no new trades)
                session.add(straddle)
                session.commit()
                continue
                
            if sell_filled:
                logger.info(f"Straddle #{straddle.id} SELL_STOP filled. Cancelling BUY_STOP #{buy_ticket}...")
                broker_executor.cancel_order(buy_ticket)
                if broker_executor.verify_cancellation(buy_ticket):
                    straddle.cancellation_confirmed = True
                    straddle.status = "FILLED"
                else:
                    telegram_notifier.notify_error("Trade Manager", f"CRITICAL: STRADDLE LEG CANCELLATION UNCONFIRMED for ticket {buy_ticket}")
                    straddle.status = "ERROR"
                session.add(straddle)
                session.commit()
                continue

            # 4-hour manual expiration logic
            straddle_age = datetime.now(timezone.utc) - straddle.created_at
            if straddle_age > timedelta(hours=4):
                logger.info(f"Straddle #{straddle.id} reached 4-hour timeout. Cancelling legs.")
                if not buy_filled and not buy_expired:
                    broker_executor.cancel_order(buy_ticket)
                if not sell_filled and not sell_expired:
                    broker_executor.cancel_order(sell_ticket)
                straddle.status = "EXPIRED"
                session.add(straddle)
                session.commit()
                continue
                
            # If both missing and we didn't expire them manually, it means user cancelled them manually
            if buy_expired and sell_expired:
                logger.info(f"Straddle #{straddle.id} no longer exists in MT5. Marking EXPIRED.")
                straddle.status = "EXPIRED"
                session.add(straddle)
                session.commit()
                continue
                
    except Exception as e:
        logger.exception(f"Straddle Monitor loop error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manage_open_trades()
    monitor_straddles()
