import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timezone, timedelta
from engine.pattern_detector import detect_fvg_order_blocks

mt5.initialize()

def simulate_filtered_momentum_runner(start_dt, end_dt, name="Period"):
    print(f"\n=======================================================")
    print(f"  TESTING CORE MOMENTUM RUNNER (WITH ADX & EXTENSION FILTERS)")
    print(f"  {name}: From {start_dt} to {end_dt}")
    print(f"=======================================================")
    
    # Fetch H1 and M15 data
    h1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start_dt - timedelta(days=5), end_dt)
    m15_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M15, start_dt - timedelta(days=2), end_dt)
    
    if h1_rates is None or m15_rates is None:
        print("Data fetch failed.")
        return
        
    h1_df = pd.DataFrame(h1_rates)
    h1_df['time_dt'] = pd.to_datetime(h1_df['time'], unit='s', utc=True)
    h1_df['ema50'] = ta.trend.ema_indicator(h1_df['close'], window=50)
    adx_ind = ta.trend.ADXIndicator(h1_df['high'], h1_df['low'], h1_df['close'], window=14)
    h1_df['adx'] = adx_ind.adx()
    h1_df['atr'] = ta.volatility.average_true_range(h1_df['high'], h1_df['low'], h1_df['close'], window=14)
    
    m15_df = pd.DataFrame(m15_rates)
    m15_df['time_dt'] = pd.to_datetime(m15_df['time'], unit='s', utc=True)
    
    # Iterate through each M15 candle in the target date range
    target_m15 = m15_df[m15_df['time_dt'] >= start_dt].copy()
    
    signals_raw = 0
    signals_adx_filtered = 0
    signals_extension_filtered = 0
    signals_approved = 0
    
    for idx, c in target_m15.iterrows():
        c_time = c['time_dt']
        
        # Get latest closed H1 candle before this M15 candle
        h1_sub = h1_df[h1_df['time_dt'] <= c_time]
        if len(h1_sub) < 50: continue
        
        h1_last = h1_sub.iloc[-1]
        h1_close = h1_last['close']
        h1_ema50 = h1_last['ema50']
        h1_adx = h1_last['adx']
        h1_atr = h1_last['atr']
        
        is_bullish = h1_close > h1_ema50
        dir_filter = "long" if is_bullish else "short"
        
        # M15 sub window for OB detection
        m15_sub = m15_df[m15_df['time_dt'] <= c_time].iloc[-40:].reset_index(drop=True)
        obs = detect_fvg_order_blocks(m15_sub, direction=dir_filter)
        target_dir = 'BULLISH' if is_bullish else 'BEARISH'
        valid_obs = [ob for ob in obs if ob['direction'] == target_dir]
        
        if valid_obs:
            signals_raw += 1
            if h1_adx < 20.0:
                signals_adx_filtered += 1
                continue
            dist_from_ema = abs(h1_close - h1_ema50)
            if dist_from_ema > 2.5 * h1_atr:
                signals_extension_filtered += 1
                continue
            signals_approved += 1

    print(f"Total Raw M15 FVG Setups Detected: {signals_raw}")
    print(f"Setups Blocked by ADX Filter (< 20.0 chop): {signals_adx_filtered}")
    print(f"Setups Blocked by Over-Extension (> 2.5x ATR): {signals_extension_filtered}")
    print(f"High-Conviction Setups Passed for Execution: {signals_approved}")

fri_start = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)
fri_end = datetime(2026, 9, 18, 23, 59, tzinfo=timezone.utc)
simulate_filtered_momentum_runner(fri_start, fri_end, "Friday (Trending Day)")

mon_start = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
mon_end = datetime.now(timezone.utc)
simulate_filtered_momentum_runner(mon_start, mon_end, "Monday (Choppy / Reversal Day)")
