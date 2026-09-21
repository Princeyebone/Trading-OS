import sys
import os
from dotenv import load_dotenv
import logging

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

# Basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_runner")

sys.path.insert(0, "c:/Users/HP/OneDrive/Desktop/tb/backend")

from engine.xagi4_trend_scalper import Xagi4TrendScalper
from engine.eusdi3_camarilla import run_camarilla_reversal
from engine.db import get_session
from app.models.config import EngineConfig
from sqlmodel import select

def test_xagi4():
    logger.info("--- Testing XAGI4 ---")
    try:
        session = get_session()
        config = session.exec(select(EngineConfig).order_by(EngineConfig.id.desc())).first()
        session.close()
        
        if not config:
            logger.error("No config found")
            return
            
        x4 = Xagi4TrendScalper()
        res = x4.check_and_execute(config)
        logger.info(f"XAGI4 Result: {res}")
    except Exception as e:
        logger.exception(f"XAGI4 CRASHED: {e}")

def test_eusdi3():
    logger.info("--- Testing EUSDI3 ---")
    try:
        res = run_camarilla_reversal()
        logger.info(f"EUSDI3 Result: {res}")
    except Exception as e:
        logger.exception(f"EUSDI3 CRASHED: {e}")

if __name__ == "__main__":
    test_xagi4()
    test_eusdi3()
