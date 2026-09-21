import sys
import os
from datetime import datetime, timezone
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

MAGIC_MAP = {
    202600: "XAGI1",  202601: "XAGI1-Swing",
    202602: "XAGI2",  202603: "XAGI3",
    202604: "XAGI4",  202700: "XAGI3",
    202800: "XAGI5",  202900: "XAGI6",
    202808: "XAGI8-IFVG", 202809: "XAGI9-3Candle",
    203000: "EUSDI6", 203100: "EUSDI7",
    203200: "GI2",    203300: "GI3",
}

positions = mt5.positions_get()
if not positions:
    print("No open positions found.")
else:
    print(f"--- OPEN POSITIONS ({len(positions)}) ---")
    current_time = datetime.now().timestamp()
    
    for p in positions:
        strat = MAGIC_MAP.get(p.magic, f"UNKNOWN_{p.magic}")
        direction = "BUY" if p.type == 0 else "SELL"
        
        # Calculate duration
        # mt5.time_current() gives the current broker server time
        broker_time = mt5.symbol_info_tick(p.symbol).time
        duration_seconds = broker_time - p.time
        minutes = int(duration_seconds // 60)
        hours = int(minutes // 60)
        rem_minutes = minutes % 60
        
        duration_str = f"{hours}h {rem_minutes}m" if hours > 0 else f"{minutes} minutes"
        
        print(f"[{strat}] {direction} {p.volume} {p.symbol} @ {p.price_open} | Profit: {p.profit} | Open For: {duration_str}")

mt5.shutdown()
