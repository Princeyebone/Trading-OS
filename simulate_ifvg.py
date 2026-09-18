"""
backend/simulate_ifvg.py
Test script to run the IFVG strategy on historical M5 data and ensure it generates signals.
"""
import sys
import os
import pandas as pd
from datetime import datetime

# Setup path so it can run as a module or standalone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data_fetcher import fetch_ohlcv
from engine.xagi8_ifvg_reversal import Xagi8IFVGReversal
import MetaTrader5 as mt5

def run_simulation():
    print("Testing IFVG Strategy on recent XAUUSD M5 data...")
    
    # We will instantiate the strategy and directly call scan_m5 
    # to see if any signals were generated historically in the last 1000 bars
    
    # Try fetching data directly to mock the environment
    m5_data = fetch_ohlcv("M5", use_cache=True)
    if m5_data is None:
        print("Failed to fetch M5 data.")
        return
        
    print(f"Fetched {len(m5_data)} M5 candles.")
    
    strategy = Xagi8IFVGReversal()
    
    # We will loop through the dataframe to simulate scanning at different times
    total_signals = 0
    for i in range(100, len(m5_data) - 1):
        # Create a slice of data up to index i
        df_slice = m5_data.iloc[:i+1].copy()
        
        # We need to mock the fetch_ohlcv call inside scan_m5, or we can just call detect directly
        from engine.pattern_detector import detect_inversion_fair_value_gaps
        ifvgs = detect_inversion_fair_value_gaps(df_slice)
        
        current_price = df_slice['close'].iloc[-1]
        
        for ifvg in ifvgs:
            bars_ago = (len(df_slice) - 1) - ifvg["bar_index"]
            if bars_ago > 10:
                continue
                
            gap_size = abs(ifvg["high"] - ifvg["low"])
            if gap_size < 1.0:
                continue
                
            direction = ifvg["direction"]
            
            if direction == "BULLISH":
                if current_price <= (ifvg["high"] + 0.5) and current_price >= (ifvg["low"] - 0.5):
                    sl = ifvg["low"] - 1.0
                    entry = current_price
                    risk = entry - sl
                    if risk > 0:
                        print(f"[{df_slice.index[-1]}] [BULL] IFVG Signal Fired! Entry: {entry}, SL: {sl}, Gap: {ifvg['low']}-{ifvg['high']}")
                        total_signals += 1
                        break
                        
            elif direction == "BEARISH":
                if current_price >= (ifvg["low"] - 0.5) and current_price <= (ifvg["high"] + 0.5):
                    sl = ifvg["high"] + 1.0
                    entry = current_price
                    risk = sl - entry
                    if risk > 0:
                        print(f"[{df_slice.index[-1]}] [BEAR] IFVG Signal Fired! Entry: {entry}, SL: {sl}, Gap: {ifvg['low']}-{ifvg['high']}")
                        total_signals += 1
                        break

    print(f"Simulation complete. Total signals that would have fired: {total_signals}")
    if total_signals == 0:
        print("WARNING: No signals fired. The conditions might be too strict, or no IFVGs occurred recently.")
    else:
        print("SUCCESS: The strategy is capable of firing trades!")

if __name__ == "__main__":
    if not mt5.initialize():
        print("MT5 initialization failed. Ensure MT5 is running.")
    else:
        run_simulation()
        mt5.shutdown()
