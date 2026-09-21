import sys
import time
import logging
import MetaTrader5 as mt5

sys.path.insert(0, "c:/Users/HP/OneDrive/Desktop/tb/backend")
from engine.trade_manager import execute_friday_killswitch
from engine.broker_executor import _init_mt5, cancel_order

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_open_wipe")

def wait_and_wipe():
    logger.info("Starting market-open wipe daemon...")
    
    while True:
        if not _init_mt5():
            logger.warning("Failed to connect to MT5. Retrying in 60s...")
            time.sleep(60)
            continue
            
        positions = mt5.positions_get()
        orders = mt5.orders_get()
        
        has_positions = bool(positions)
        has_orders = bool(orders)
        
        if not has_positions and not has_orders:
            logger.info("\U0001f389 All positions and orders are closed! Exiting daemon.")
            break
            
        logger.info(f"Detected {len(positions) if positions else 0} positions and {len(orders) if orders else 0} orders.")
        logger.info("Attempting wipe...")
        
        # 1. Attempt to close positions
        if has_positions:
            execute_friday_killswitch()
            
        # 2. Attempt to cancel orders
        if has_orders:
            for o in orders:
                logger.info(f"Cancelling pending order #{o.ticket}")
                cancel_order(o.ticket)
                
        logger.info("Wipe cycle completed. Waiting 30s to recheck...")
        time.sleep(30)

if __name__ == "__main__":
    wait_and_wipe()
