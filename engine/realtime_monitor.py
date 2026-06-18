"""
engine/realtime_monitor.py — 1-Minute cycle for deterministic execution and tape monitoring.
"""
import logging
import time
from sqlmodel import Session, select
from app.database import engine
from app.models.trades import StraddlePair
from engine import broker_executor, market_tape_monitor, telegram_notifier

logger = logging.getLogger("engine.realtime_monitor")

def check_active_straddles():
    with Session(engine) as session:
        active_straddles = session.exec(
            select(StraddlePair).where(StraddlePair.status == "ACTIVE")
        ).all()
        
        if not active_straddles:
            return
            
        spread_points = broker_executor.check_spread()
        
        for pair in active_straddles:
            # 1. Anti-Slippage Spread Check
            if spread_points > 25.0:
                logger.warning(f"Spread spiked to {spread_points} points. Aborting Straddle {pair.id}")
                broker_executor.cancel_order(pair.buy_order_id)
                broker_executor.cancel_order(pair.sell_order_id)
                pair.status = "CANCELLED"
                
                # Check if it actually cancelled
                b_cancel = broker_executor.verify_cancellation(pair.buy_order_id)
                s_cancel = broker_executor.verify_cancellation(pair.sell_order_id)
                pair.cancellation_confirmed = (b_cancel and s_cancel)
                
                session.add(pair)
                session.commit()
                
                try:
                    telegram_notifier.notify_error(
                        "CRITICAL: SPREAD ABORT", 
                        f"Spread spiked to {spread_points} points.\n"
                        f"Aborted Straddle Pair #{pair.id}\n"
                        f"Buy Ticket: {pair.buy_order_id} (Cancel Success: {b_cancel})\n"
                        f"Sell Ticket: {pair.sell_order_id} (Cancel Success: {s_cancel})"
                    )
                except Exception:
                    pass
                continue
                
            # 2. Straddle Fill Confirmation (OCO - One Cancels Other)
            status_dict = broker_executor.check_straddle_status(pair.buy_order_id, pair.sell_order_id)
            
            if status_dict["buy_filled"] and status_dict["sell_filled"]:
                logger.error(f"CRITICAL: Both straddle legs filled for pair {pair.id}")
                pair.status = "WHIPSAW_ERROR"
                session.add(pair)
                session.commit()
                try:
                    telegram_notifier.notify_error(
                        "CRITICAL: WHIPSAW ERROR",
                        f"BOTH STRADDLE LEGS FILLED!\nPair #{pair.id}\nMANUAL INTERVENTION REQUIRED."
                    )
                except Exception:
                    pass
            elif status_dict["buy_filled"]:
                logger.info(f"Straddle Buy triggered. Cancelling Sell {pair.sell_order_id}")
                broker_executor.cancel_order(pair.sell_order_id)
                pair.status = "FILLED"
                session.add(pair)
                session.commit()
                try:
                    telegram_notifier.notify_error("Real-Time Monitor", "Straddle BUY Filled. OCO Cancelled Sell Stop.")
                except Exception:
                    pass
            elif status_dict["sell_filled"]:
                logger.info(f"Straddle Sell triggered. Cancelling Buy {pair.buy_order_id}")
                broker_executor.cancel_order(pair.buy_order_id)
                pair.status = "FILLED"
                session.add(pair)
                session.commit()
                try:
                    telegram_notifier.notify_error("Real-Time Monitor", "Straddle SELL Filled. OCO Cancelled Buy Stop.")
                except Exception:
                    pass
            elif status_dict["buy_expired"] and status_dict["sell_expired"]:
                logger.info(f"Both pending orders expired/cancelled for Straddle {pair.id}")
                pair.status = "EXPIRED"
                session.add(pair)
                session.commit()


import os

def write_heartbeat():
    """Write dead-man switch timestamp to file."""
    try:
        with open(".realtime_heartbeat", "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        logger.error(f"Heartbeat write failed: {e}")

def run_monitor_cycle():
    logger.info("Realtime monitor cycle starting...")
    
    # 0. Heartbeat dead-man switch
    write_heartbeat()
    
    # 1. Straddle risk management checks (Highest Priority)
    check_active_straddles()

    # 2. Tape event detection (Lower Priority)
    market_tape_monitor.detect_tape_events()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )
    
    logger.info("============================================================")
    logger.info("Starting realtime_monitor daemon (1-minute cycle)")
    logger.info("============================================================")
    
    while True:
        try:
            run_monitor_cycle()
        except Exception as e:
            logger.error(f"Realtime monitor crash: {e}")
            
        time.sleep(60)
