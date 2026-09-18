import sys
import os
import MetaTrader5 as mt5
from dotenv import load_dotenv

from engine.xagi9_3_candle_momentum import Xagi9ThreeCandleMomentum
from engine.data_fetcher import fetch_ohlcv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")
mt5.initialize(login=int(os.getenv("MT5_LOGIN", 0)), password=os.getenv("MT5_PASSWORD", ""), server=os.getenv("MT5_SERVER", ""))

xagi9 = Xagi9ThreeCandleMomentum()
m5_data = fetch_ohlcv("M5", use_cache=False)

c1 = m5_data.iloc[-3]
c2 = m5_data.iloc[-2]
c3 = m5_data.iloc[-1]

c1_body = c1['close'] - c1['open']
c2_body = c2['close'] - c2['open']

is_bullish_momentum = (c1_body >= xagi9.min_body_size) and (c2_body >= xagi9.min_body_size)
is_bearish_momentum = (c1_body <= -xagi9.min_body_size) and (c2_body <= -xagi9.min_body_size)

print("C1 (index -3):", c1.name, "Body:", c1_body)
print("C2 (index -2):", c2.name, "Body:", c2_body)
print("C3 (index -1):", c3.name, "Open:", c3['open'])

print("Bullish Momentum:", is_bullish_momentum)
print("Bearish Momentum:", is_bearish_momentum)

current_price_ask = mt5.symbol_info_tick("XAUUSD").ask
current_price_bid = mt5.symbol_info_tick("XAUUSD").bid
print("Current Ask:", current_price_ask)
print("Current Bid:", current_price_bid)

if is_bullish_momentum:
    print("Price > C3 Open?", current_price_ask > c3['open'])
    sl = c2['low'] - xagi9.sl_buffer
    risk = current_price_ask - sl
    print("SL:", sl, "Risk:", risk)
    print("Risk Valid?", 0 < risk < 5.0)

if is_bearish_momentum:
    print("Price < C3 Open?", current_price_bid < c3['open'])
    sl = c2['high'] + xagi9.sl_buffer
    risk = sl - current_price_bid
    print("SL:", sl, "Risk:", risk)
    print("Risk Valid?", 0 < risk < 5.0)

mt5.shutdown()
