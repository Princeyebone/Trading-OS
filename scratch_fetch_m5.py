import sys
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

# 3 hours = 36 M5 candles
rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 36)
if rates is None:
    print("No rates retrieved")
    mt5.shutdown()
    sys.exit(1)

df = pd.DataFrame(rates)
df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

print("TIME (UTC)|OPEN|CLOSE|HIGH|LOW|DIRECTION|BODY_PIPS")
for _, row in df.iterrows():
    time_str = row['time'].strftime('%Y-%m-%d %H:%M:%S')
    direction = "BULLISH" if row['close'] > row['open'] else "BEARISH" if row['close'] < row['open'] else "DOJI"
    body_pips = abs(row['close'] - row['open']) * 10
    print(f"{time_str}|{row['open']:.2f}|{row['close']:.2f}|{row['high']:.2f}|{row['low']:.2f}|{direction}|{body_pips:.1f}")

mt5.shutdown()
