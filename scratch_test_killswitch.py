import sys
import logging
sys.path.insert(0, "c:/Users/HP/OneDrive/Desktop/tb/backend")

from engine.trade_manager import execute_friday_killswitch
from engine.db import get_session

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("engine")
    logger.setLevel(logging.INFO)
    
    # Just run it to test syntax and DB connections
    print("Testing execute_friday_killswitch()...")
    execute_friday_killswitch()
    print("Done.")
