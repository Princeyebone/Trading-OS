import pandas as pd
import ta
import MetaTrader5 as mt5
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.pattern_detector import detect_order_blocks

if mt5.initialize():
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M15, 0, 1000)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['ema200'] = ta.trend.ema_indicator(df['close'], window=200)
    
    found = 0
    for i in range(200, 300):
        c = df.iloc[i]
        is_bullish = c['close'] > c['ema200']
        td = 'BULLISH' if is_bullish else 'BEARISH'
        
        window = df.iloc[i-40:i].reset_index(drop=True)
        obs = detect_order_blocks(window, direction=td.lower())
        v = [ob for ob in obs if ob['direction'] == td]
        if v:
            found += 1
            
    print(f"Found valid OBs in {found} out of 100 iterations.")
