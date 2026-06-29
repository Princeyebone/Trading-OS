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
import time

logger = logging.getLogger("engine.trade_manager")

# Cache to prevent Telegram spam (only notify every 10 pips of locked profit)
_last_notified_lock = {}

TP1_THRESHOLD_PIPS = 10.0   # First harvest: 10 pips (1.0 Gold point)
TP1_CLOSE_PERCENT   = 25.0  # Lock 25% at TP1, leave 75% running
TRAIL_DISTANCE_PIPS = 30.0  # Tightened trail — runner follows within 30 pips
BUFFER_PIPS = 5.0

import pandas as pd
import time

_last_log_time = {}

def sweep_orphans(session):
    """
    Checks MT5 for natively open positions that the DB doesn't know about.
    If found, injects them as a Trade so they can be trailed.
    """
    mt5_positions = mt5.positions_get()
    if not mt5_positions:
        return
        
    for p in mt5_positions:
        ticket = p.ticket
        existing = session.exec(select(Trade).where(Trade.broker_order_id == str(ticket))).first()
        if not existing:
            logger.warning(f"Orphan Sweeper: Found untracked MT5 position {ticket} (Magic {p.magic}). Adopting...")
            direction = "LONG" if p.type == mt5.POSITION_TYPE_BUY else "SHORT"
            entry_price = p.price_open
            new_trade = Trade(
                direction=direction,
                planned_entry=entry_price,
                actual_entry=entry_price,
                stop_loss=p.sl if p.sl > 0 else (entry_price - 10.0 if direction=="LONG" else entry_price + 10.0),
                take_profit_1=p.tp if p.tp > 0 else (entry_price + 50.0 if direction=="LONG" else entry_price - 50.0),
                lot_size=p.volume,
                status="OPEN",
                broker_order_id=str(ticket),
                broker="MT5",
                highest_profit_pips=0.0,
                locked_profit_pips=0.0
            )
            session.add(new_trade)
            session.commit()
            logger.info(f"Orphan Sweeper: Successfully adopted Trade #{new_trade.id} into DB.")

def manage_open_trades():
    """
    Check all OPEN trades in the database against live market prices.
    Executes partial closures, BE moves, and trailing stops.
    """
    session = get_session()
    try:
        # Use FOR UPDATE to lock rows and prevent scheduler conflicts
        open_trades = session.exec(select(Trade).where(Trade.status.in_(["OPEN", "PENDING"])).with_for_update()).all()
        if not open_trades:
            return

        # Initialize MT5 to fetch live prices
        if not broker_executor._init_mt5():
            logger.error("Trade Manager: MT5 not initialized, skipping cycle.")
            return
            
        sweep_orphans(session)
            
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
                # If it's a pending trade, check if the limit order is still sitting there
                if trade.status == "PENDING":
                    mt5_order = mt5.orders_get(ticket=ticket)
                    if mt5_order:
                        order_price = mt5_order[0].price_open
                        magic = mt5_order[0].magic
                        current_price = live_ask if trade.direction == "LONG" else live_bid
                        dist_pips = abs(current_price - order_price) * 10.0
                        import time
                        now = time.time()
                        if now - _last_log_time.get(f"{trade.id}_pending", 0) >= 5.0:
                            if magic == 202603:
                                logger.info(f"⏳ [M5 Runner Monitor] Trade #{trade.id} PENDING Limit Order: {dist_pips:.1f} pts away from 50% Pullback ({order_price:.2f})")
                            elif magic == 202604:
                                logger.info(f"⏳ [M15 Momentum Monitor] Trade #{trade.id} PENDING Limit Order: {dist_pips:.1f} pts away from 50% Pullback ({order_price:.2f})")
                            else:
                                logger.info(f"⏳ [M15 FVG Sniper Monitor] Trade #{trade.id} PENDING Limit Order: {dist_pips:.1f} pts away from entry ({order_price:.2f})")
                            _last_log_time[f"{trade.id}_pending"] = now
                    else:
                        # Order is gone and not a position (cancelled or expired)
                        trade.status = "CANCELLED"
                        session.add(trade)
                        session.commit()
                continue
                
            if trade.status == "PENDING":
                trade.status = "OPEN"
                session.add(trade)
                session.commit()
                logger.info(f"🟢 Pending trade #{trade.id} has been FILLED and is now OPEN!")
                if mt5_pos[0].magic in [202602, 202603, 202604]:
                    strat_name = "FVG Sniper" if mt5_pos[0].magic == 202602 else "M5 Runner" if mt5_pos[0].magic == 202603 else "M15 Runner"
                    telegram_notifier.notify_trade_executed(
                        direction=trade.direction,
                        entry=entry,
                        stop_loss=trade.stop_loss,
                        tp1=trade.take_profit_1 or 0.0,
                        tp2=0.0,
                        lot_size=trade.lot_size,
                        confidence=100,
                        order_id=trade.broker_order_id,
                        reasoning=f"{strat_name} Limit Order Filled"
                    )
                
            # Skip tight ratcheting TP for Macro Swing trades
            if mt5_pos[0].magic == 202601:
                continue
                
            # M15 FVG Sniper Trailing Logic (Magic 202602)
            if mt5_pos[0].magic == 202602:
                # Use a tighter 15-pip trailing stop for more consistent payouts
                MOMENTUM_TRAIL_PIPS = 15.0
                
                # Calculate live profit in pips
                if trade.direction == "LONG":
                    profit_pips = (live_bid - entry) * 10
                else:
                    profit_pips = (entry - live_ask) * 10
                    
                dirty = False
                if profit_pips > trade.highest_profit_pips:
                    trade.highest_profit_pips = profit_pips
                    dirty = True
                    
                # New trailing stop level (highest profit - 30 pips)
                if trade.highest_profit_pips >= MOMENTUM_TRAIL_PIPS:
                    locked_pips = trade.highest_profit_pips - MOMENTUM_TRAIL_PIPS
                    if locked_pips > trade.locked_profit_pips:
                        trade.locked_profit_pips = locked_pips
                        dirty = True
                        
                        # Move SL natively
                        new_sl = entry + (locked_pips / 10.0) if trade.direction == "LONG" else entry - (locked_pips / 10.0)
                        broker_executor.modify_position_sl(ticket, new_sl)
                        logger.info(f"🚀 FVG Sniper Trailing SL moved to +{locked_pips:.1f} pips")
                        if locked_pips >= _last_notified_lock.get(trade.id, 0) + 10.0:
                            dollar_val = locked_pips * (trade.lot_size * 10.0)
                            telegram_notifier.notify_info("FVG Sniper Locked", f"🚀 Trade #{trade.id} LOCKED +{locked_pips:.1f} pips (+${dollar_val:.2f})")
                            _last_notified_lock[trade.id] = locked_pips
                
                # Hard close if it reverses past the lock
                if trade.locked_profit_pips > 0 and profit_pips <= trade.locked_profit_pips:
                    logger.info(f"🎯 FVG Sniper Trailing Stop HIT! Closing at +{trade.locked_profit_pips:.1f} pips.")
                    success = broker_executor.close_position(ticket)
                    dirty = True
                    if success:
                        dollar_val = trade.locked_profit_pips * (trade.lot_size * 10.0)
                        telegram_notifier.notify_success("FVG Sniper Closed", f"🎯 Trade #{trade.id} closed at +{trade.locked_profit_pips:.1f} pips (+${dollar_val:.2f})!")
                        if trade.id in _last_notified_lock: del _last_notified_lock[trade.id]
                    
                if dirty:
                    session.add(trade)
                    session.commit()
                    
                logger.info(f"📈 [M15 FVG Sniper Monitor] Trade #{trade.id}: ACTIVE: PnL {profit_pips:+.1f} pips | Trail Lock = +{trade.locked_profit_pips:.1f} pips | Target = Open (Trail 30 pips)")
                continue

            # M5 Momentum Runner Trailing Logic (Magic 202603)
            if mt5_pos[0].magic == 202603:
                # Use a tighter 10-pip trailing stop for the M5 timeframe
                M5_TRAIL_PIPS = 10.0
                
                # Calculate live profit in pips
                if trade.direction == "LONG":
                    profit_pips = (live_bid - entry) * 10
                else:
                    profit_pips = (entry - live_ask) * 10
                    
                dirty = False
                if profit_pips > trade.highest_profit_pips:
                    trade.highest_profit_pips = profit_pips
                    dirty = True
                    
                # New trailing stop level (highest profit - 20 pips)
                if trade.highest_profit_pips >= M5_TRAIL_PIPS:
                    locked_pips = trade.highest_profit_pips - M5_TRAIL_PIPS
                    if locked_pips > trade.locked_profit_pips:
                        trade.locked_profit_pips = locked_pips
                        dirty = True
                        
                        # Move SL natively
                        new_sl = entry + (locked_pips / 10.0) if trade.direction == "LONG" else entry - (locked_pips / 10.0)
                        broker_executor.modify_position_sl(ticket, new_sl)
                        logger.info(f"🚀 M5 Runner Trailing SL moved to +{locked_pips:.1f} pips")
                        if locked_pips >= _last_notified_lock.get(trade.id, 0) + 10.0:
                            dollar_val = locked_pips * (trade.lot_size * 10.0)
                            telegram_notifier.notify_info("M5 Runner Locked", f"🚀 Trade #{trade.id} LOCKED +{locked_pips:.1f} pips (+${dollar_val:.2f})")
                            _last_notified_lock[trade.id] = locked_pips
                
                # Hard close if it reverses past the lock
                if trade.locked_profit_pips > 0 and profit_pips <= trade.locked_profit_pips:
                    logger.info(f"🎯 M5 Runner Trailing Stop HIT! Closing at +{trade.locked_profit_pips:.1f} pips.")
                    success = broker_executor.close_position(ticket)
                    dirty = True
                    if success:
                        dollar_val = trade.locked_profit_pips * (trade.lot_size * 10.0)
                        telegram_notifier.notify_success("M5 Runner Closed", f"🎯 Trade #{trade.id} closed at +{trade.locked_profit_pips:.1f} pips (+${dollar_val:.2f})!")
                        if trade.id in _last_notified_lock: del _last_notified_lock[trade.id]
                    
                if dirty:
                    session.add(trade)
                    session.commit()
                    
                logger.info(f"📈 [M5 Runner Monitor] Trade #{trade.id}: ACTIVE: PnL {profit_pips:+.1f} pips | Trail Lock = +{trade.locked_profit_pips:.1f} pips | Target = Open (Trail 20 pips)")
                continue

            # XAGI4 Trend Scalper Logic (Magic 202800)
            if mt5_pos[0].magic == 202800:
                if trade.opened_at:
                    trade_age_mins = (datetime.now(timezone.utc) - trade.opened_at.replace(tzinfo=timezone.utc)).total_seconds() / 60.0
                    
                    if trade.direction == "LONG":
                        profit_pips = (live_bid - entry) * 10
                    else:
                        profit_pips = (entry - live_ask) * 10
                    
                    # 20-Minute Forced Close Rule
                    if trade_age_mins > 20 and profit_pips < 0:
                        logger.info(f"⏰ [XAGI4] Trade #{trade.id} aged {trade_age_mins:.1f} mins and is negative ({profit_pips:.1f} pips). Force Closing!")
                        success = broker_executor.close_position(ticket)
                        if success:
                            telegram_notifier.notify_success("XAGI4 Force Close", f"⏰ Trade #{trade.id} Force Closed after 20 mins to prevent trend drag. Loss: {profit_pips:.1f} pips.")
                        continue
                # If not forced closed, let it fall through to the generic Step TP logic

            # M15 Momentum Sibling Trailing Logic (Magic 202604)
            if mt5_pos[0].magic == 202604:
                # Use a tighter 15-pip trailing stop for the M15 timeframe
                M15_TRAIL_PIPS = 15.0
                
                # Calculate live profit in pips
                if trade.direction == "LONG":
                    profit_pips = (live_bid - entry) * 10
                else:
                    profit_pips = (entry - live_ask) * 10
                    
                dirty = False
                if profit_pips > trade.highest_profit_pips:
                    trade.highest_profit_pips = profit_pips
                    dirty = True
                    
                # New trailing stop level (highest profit - 30 pips)
                if trade.highest_profit_pips >= M15_TRAIL_PIPS:
                    locked_pips = trade.highest_profit_pips - M15_TRAIL_PIPS
                    if locked_pips > trade.locked_profit_pips:
                        trade.locked_profit_pips = locked_pips
                        dirty = True
                        
                        # Move SL natively
                        new_sl = entry + (locked_pips / 10.0) if trade.direction == "LONG" else entry - (locked_pips / 10.0)
                        broker_executor.modify_position_sl(ticket, new_sl)
                        logger.info(f"🚀 M15 Momentum Sibling Trailing SL moved to +{locked_pips:.1f} pips")
                        if locked_pips >= _last_notified_lock.get(trade.id, 0) + 10.0:
                            dollar_val = locked_pips * (trade.lot_size * 10.0)
                            telegram_notifier.notify_info("M15 Runner Locked", f"🚀 Trade #{trade.id} LOCKED +{locked_pips:.1f} pips (+${dollar_val:.2f})")
                            _last_notified_lock[trade.id] = locked_pips
                
                # Hard close if it reverses past the lock
                if trade.locked_profit_pips > 0 and profit_pips <= trade.locked_profit_pips:
                    logger.info(f"🎯 M15 Momentum Sibling Trailing Stop HIT! Closing at +{trade.locked_profit_pips:.1f} pips.")
                    success = broker_executor.close_position(ticket)
                    dirty = True
                    if success:
                        dollar_val = trade.locked_profit_pips * (trade.lot_size * 10.0)
                        telegram_notifier.notify_success("M15 Runner Closed", f"🎯 Trade #{trade.id} closed at +{trade.locked_profit_pips:.1f} pips (+${dollar_val:.2f})!")
                        if trade.id in _last_notified_lock: del _last_notified_lock[trade.id]
                    
                if dirty:
                    session.add(trade)
                    session.commit()
                    
                logger.info(f"📈 [M15 Momentum Monitor] Trade #{trade.id}: ACTIVE: PnL {profit_pips:+.1f} pips | Trail Lock = +{trade.locked_profit_pips:.1f} pips | Target = Open (Trail 30 pips)")
                continue
                
            # Determine Lock Configuration based on Signal
            if trade.signal_id:
                from app.models.signals import Signal
                sig = session.get(Signal, trade.signal_id)
                if sig and sig.session == "SCALP":
                    start_lock_pips = 10.0
                    step_gain_pips = 10.0
                    step_lock_pips = 10.0
                else:
                    start_lock_pips = 10.0
                    step_gain_pips = 20.0
                    step_lock_pips = 20.0
            else:
                start_lock_pips = 10.0
                step_gain_pips = 20.0
                step_lock_pips = 20.0
                
            # Calculate live profit in pips
            if trade.direction == "LONG":
                profit_pips = (live_bid - entry) * 10
            else:
                profit_pips = (entry - live_ask) * 10
                
            trade_type = "SCALP" if step_gain_pips == 10.0 else "TCP"
            logger.info(f"📊 [Step TP Monitor] Trade #{trade.id} ({trade_type}): ACTIVE: PnL {profit_pips:+.1f} pips | Locked = {trade.locked_profit_pips:.1f} pips")
                
            # Update highest profit
            dirty = False
            if profit_pips > trade.highest_profit_pips:
                trade.highest_profit_pips = profit_pips
                dirty = True
                
            # --- Dynamic Ratcheting TP Logic ---
            # 1. Calculate the new lock level based on dynamic steps
            new_lock = 0.0
            if trade_type == "TCP":
                profit_pts = profit_pips / 10.0
                if profit_pts >= 1.0:
                    step = 1.0 + float(int((profit_pts - 1.0) // 2.0)) * 2.0
                    if step == 1.0:
                        new_lock_pts = 1.0
                    elif step == 3.0:
                        new_lock_pts = 2.0
                    elif step == 5.0:
                        new_lock_pts = 4.0
                    else:
                        new_lock_pts = step - 2.0
                    new_lock = new_lock_pts * 10.0
            else:
                if profit_pips >= start_lock_pips:
                    steps = int((profit_pips - start_lock_pips) // step_gain_pips)
                    new_lock = start_lock_pips + (steps * step_lock_pips)
            
            if new_lock > trade.locked_profit_pips:
                trade.locked_profit_pips = new_lock
                dirty = True
                logger.info(f"🔒 LOCKED +{trade.locked_profit_pips:.1f} pips profit for trade #{trade.id}")
                
                # Debounce Telegram (only notify every 10 pips)
                if new_lock >= _last_notified_lock.get(trade.id, 0) + 10.0:
                    telegram_notifier.notify_info("Step TP", f"🔒 Trade #{trade.id} (Ticket #{ticket}) LOCKED +{trade.locked_profit_pips:.1f} pips")
                    _last_notified_lock[trade.id] = new_lock
                
                # Optionally move SL natively to protect MT5 state if server dies
                # (Break-even + locked profit - buffer)
                protect_pips = trade.locked_profit_pips - (step_gain_pips * 0.5)
                if protect_pips >= 0:
                    new_sl = entry + (protect_pips / 10.0) if trade.direction == "LONG" else entry - (protect_pips / 10.0)
                    broker_executor.modify_position_sl(ticket, new_sl)
            
            # 2. Check for Reversal (Close Condition)
            if trade.locked_profit_pips > 0 and profit_pips < trade.locked_profit_pips:
                logger.info(f"🎯 STEP TP TRIGGERED for trade #{trade.id}! Reversal detected. Closing at locked {trade.locked_profit_pips:.1f} pips.")
                success = broker_executor.close_position(ticket)
                if success:
                    dirty = True
                    telegram_notifier.notify_success("Step TP Hit", f"🎯 Trade #{trade.id} (Ticket #{ticket}) closed at +{trade.locked_profit_pips:.1f} pips!")
                    if trade.id in _last_notified_lock:
                        del _last_notified_lock[trade.id]
            
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
