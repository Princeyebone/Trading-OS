import sys
import os
import MetaTrader5 as mt5
from dotenv import load_dotenv
from sqlmodel import select, Session
from app.database import engine
from app.models.config import EngineConfig

from engine.xagi9_3_candle_momentum import Xagi9ThreeCandleMomentum
from engine.xagi8_ifvg_reversal import Xagi8IFVGReversal

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")
login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed")
    sys.exit(1)

with Session(engine) as session:
    config = session.exec(select(EngineConfig).order_by(EngineConfig.id.desc())).first()
    print("Config active:", config.is_active if config else "No Config")

print("\n--- Testing XAGI9 ---")
xagi9 = Xagi9ThreeCandleMomentum()
print("Has open trade?", xagi9._has_open_trade())
signals9 = xagi9.scan_m5()
print("Signals found:", signals9)

print("\n--- Testing XAGI8 ---")
xagi8 = Xagi8IFVGReversal()
print("Has open trade?", xagi8._has_open_trade())
signals8 = xagi8.scan_m5()
print("Signals found:", signals8)

mt5.shutdown()
