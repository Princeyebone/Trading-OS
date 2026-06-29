import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import os
import time
from datetime import datetime

# MT5 Connection parameters
MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "0"))
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")
SYMBOL = "EURUSD"

# Constants
SPREAD_PIPS = 1.0  # Rigorous 1.0 pip penalty (spread + commission)
NUM_CANDLES = 30000

def _init_mt5():
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        return False
    return True

def calculate_structural_features(df):
    c = df['close']
    h = df['high']
    l = df['low']
    o = df['open']
    
    # 1. ATR (14)
    tr = pd.concat([h - l, abs(h - c.shift()), abs(l - c.shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # 2. Daily Open & Pivots & Session Highs
    # We will approximate Daily/Session features based on datetime
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    
    # Daily Open
    daily_open = df.groupby('date')['open'].transform('first')
    df['daily_open'] = daily_open
    
    # Asian Session High/Low (00:00 - 07:00)
    asian_mask = (df['hour'] >= 0) & (df['hour'] < 7)
    df['asian_high'] = df.loc[asian_mask].groupby('date')['high'].transform('max')
    df['asian_low'] = df.loc[asian_mask].groupby('date')['low'].transform('min')
    df['asian_high'] = df.groupby('date')['asian_high'].ffill().bfill()
    df['asian_low'] = df.groupby('date')['asian_low'].ffill().bfill()
    
    # London Session High/Low (07:00 - 12:00)
    lon_mask = (df['hour'] >= 7) & (df['hour'] < 12)
    df['lon_high'] = df.loc[lon_mask].groupby('date')['high'].transform('max')
    df['lon_low'] = df.loc[lon_mask].groupby('date')['low'].transform('min')
    df['lon_high'] = df.groupby('date')['lon_high'].ffill().bfill()
    df['lon_low'] = df.groupby('date')['lon_low'].ffill().bfill()
    
    # Camarilla Pivots (Previous day H, L, C)
    daily_h = df.groupby('date')['high'].transform('max').shift(1)
    daily_l = df.groupby('date')['low'].transform('min').shift(1)
    daily_c = df.groupby('date')['close'].transform('last').shift(1)
    
    # Camarilla formulas
    range_dl = daily_h - daily_l
    df['cam_r3'] = daily_c + range_dl * 1.1 / 4
    df['cam_s3'] = daily_c - range_dl * 1.1 / 4
    
    # 3. Keltner Channels (20, 2 ATR)
    df['sma20'] = c.rolling(20).mean()
    df['kc_upper'] = df['sma20'] + (2 * df['atr'])
    df['kc_lower'] = df['sma20'] - (2 * df['atr'])
    
    # 4. Bollinger Bands (20, 2.0 SD)
    df['std20'] = c.rolling(20).std()
    df['bb_upper'] = df['sma20'] + (2 * df['std20'])
    df['bb_lower'] = df['sma20'] - (2 * df['std20'])
    
    # 5. Volatility Squeeze (TTM) -> True if BB is inside KC
    df['squeeze'] = (df['bb_upper'] < df['kc_upper']) & (df['bb_lower'] > df['kc_lower'])
    
    # 6. VWAP Proxy (SMA 50 of Typical Price) + 3 SD
    tp = (h + l + c) / 3
    df['vwap'] = tp.rolling(50).mean()
    df['vwap_std'] = tp.rolling(50).std()
    df['vwap_u3'] = df['vwap'] + (3 * df['vwap_std'])
    df['vwap_l3'] = df['vwap'] - (3 * df['vwap_std'])
    
    # 7. Highest High / Lowest Low (40 bars) for Turtle Soup
    df['hh40'] = h.rolling(40).max().shift(1)
    df['ll40'] = l.rolling(40).min().shift(1)
    
    # 8. Fair Value Gaps (FVG)
    # Bullish FVG: Low of candle i > High of candle i-2
    df['bull_fvg'] = l > h.shift(2)
    # Bearish FVG: High of candle i < Low of candle i-2
    df['bear_fvg'] = h < l.shift(2)
    
    return df.dropna().reset_index(drop=True)

# --- 10 Structural Logics ---
# Signal returns: 1 (Long), -1 (Short), 0 (None)

def s1_london_breakout(df, i):
    curr = df.iloc[i]
    if curr['hour'] == 7: # Only trigger right at London Open
        if curr['close'] > curr['asian_high']: return 1
        if curr['close'] < curr['asian_low']: return -1
    return 0

def s2_ny_continuation(df, i):
    curr = df.iloc[i]
    if curr['hour'] == 13: # Around NY Open
        # If London closed above Daily Open, buy NY breakout
        if curr['close'] > curr['daily_open'] and curr['close'] > curr['lon_high']: return 1
        # If London closed below Daily Open, sell NY breakout
        if curr['close'] < curr['daily_open'] and curr['close'] < curr['lon_low']: return -1
    return 0

def s3_dead_zone_drift(df, i):
    curr = df.iloc[i]
    if curr['hour'] == 20: # Low volatility dead zone
        # Fade the daily trend
        if curr['close'] > curr['daily_open']: return -1
        if curr['close'] < curr['daily_open']: return 1
    return 0

def s4_fvg_rejection(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    # If there was a bullish FVG recently, and price dipped into it and rejected
    if df['bull_fvg'].iloc[i-5:i].any():
        if curr['low'] < prev['low'] and curr['close'] > curr['open']: return 1
    if df['bear_fvg'].iloc[i-5:i].any():
        if curr['high'] > prev['high'] and curr['close'] < curr['open']: return -1
    return 0

def s5_turtle_soup(df, i):
    curr = df.iloc[i]
    # Price breaks HH40 but closes below it
    if curr['high'] > curr['hh40'] and curr['close'] < curr['hh40']:
        return -1
    # Price breaks LL40 but closes above it
    if curr['low'] < curr['ll40'] and curr['close'] > curr['ll40']:
        return 1
    return 0

def s6_daily_open_mean_rev(df, i):
    curr = df.iloc[i]
    # If price is > 1.5 ATR from Daily Open, fade it
    if curr['close'] > curr['daily_open'] + (1.5 * curr['atr']): return -1
    if curr['close'] < curr['daily_open'] - (1.5 * curr['atr']): return 1
    return 0

def s7_vwap_3sd_fade(df, i):
    curr = df.iloc[i]
    if curr['close'] > curr['vwap_u3']: return -1
    if curr['close'] < curr['vwap_l3']: return 1
    return 0

def s8_keltner_reversion(df, i):
    curr = df.iloc[i]
    # Reversion to SMA20
    if curr['low'] < curr['kc_lower'] and curr['close'] > curr['kc_lower']: return 1
    if curr['high'] > curr['kc_upper'] and curr['close'] < curr['kc_upper']: return -1
    return 0

def s9_camarilla_reversal(df, i):
    curr = df.iloc[i]
    # Fade R3/S3
    if curr['high'] > curr['cam_r3'] and curr['close'] < curr['cam_r3']: return -1
    if curr['low'] < curr['cam_s3'] and curr['close'] > curr['cam_s3']: return 1
    return 0

def s10_ttm_squeeze_breakout(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    # Squeeze releases
    if prev['squeeze'] == True and curr['squeeze'] == False:
        if curr['close'] > curr['sma20']: return 1
        if curr['close'] < curr['sma20']: return -1
    return 0

STRATEGIES = [
    ("1_London_Breakout", s1_london_breakout, 1.5, 2.0),
    ("2_NY_Continuation", s2_ny_continuation, 1.5, 2.0),
    ("3_Dead_Zone_Drift", s3_dead_zone_drift, 1.0, 1.0),
    ("4_FVG_Rejection", s4_fvg_rejection, 1.0, 2.0),
    ("5_Turtle_Soup", s5_turtle_soup, 1.0, 2.0),
    ("6_Daily_Open_Fade", s6_daily_open_mean_rev, 1.5, 1.5),
    ("7_VWAP_3SD_Fade", s7_vwap_3sd_fade, 1.0, 1.5),
    ("8_Keltner_Reversion", s8_keltner_reversion, 1.0, 1.5),
    ("9_Camarilla_Reversal", s9_camarilla_reversal, 1.0, 2.0),
    ("10_TTM_Squeeze_BO", s10_ttm_squeeze_breakout, 1.5, 3.0)
]

def simulate_strategy(df, strat_tuple):
    name, logic_func, sl_mult, tp_mult = strat_tuple
    
    trades = []
    pos = None
    entry = 0
    sl = 0
    tp = 0
    
    open_p = df['open'].values
    high_p = df['high'].values
    low_p = df['low'].values
    atr_v = df['atr'].values
    
    for i in range(1, len(df)):
        if pos:
            if pos == 'LONG':
                if low_p[i] <= sl:
                    trades.append((sl - entry) * 10000 - SPREAD_PIPS)
                    pos = None
                elif high_p[i] >= tp:
                    trades.append((tp - entry) * 10000 - SPREAD_PIPS)
                    pos = None
            elif pos == 'SHORT':
                if high_p[i] >= sl:
                    trades.append((entry - sl) * 10000 - SPREAD_PIPS)
                    pos = None
                elif low_p[i] <= tp:
                    trades.append((entry - tp) * 10000 - SPREAD_PIPS)
                    pos = None
            continue
            
        signal = logic_func(df, i-1)
        if signal == 1:
            pos = 'LONG'
            entry = open_p[i]
            sl = entry - (atr_v[i-1] * sl_mult)
            tp = entry + (atr_v[i-1] * tp_mult)
        elif signal == -1:
            pos = 'SHORT'
            entry = open_p[i]
            sl = entry + (atr_v[i-1] * sl_mult)
            tp = entry - (atr_v[i-1] * tp_mult)
            
    if not trades:
        return {"Trades": 0, "WinRate": 0, "ProfitFactor": 0.0, "NetPips": 0}
        
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
    net_pips = sum(trades)
    
    return {
        "Trades": len(trades),
        "WinRate": round(win_rate, 1),
        "ProfitFactor": round(pf, 2),
        "NetPips": round(net_pips, 1)
    }

def main():
    if not _init_mt5():
        print("Failed to init MT5")
        return
        
    timeframes = {
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1
    }
    
    results = []
    
    for tf_name, tf_val in timeframes.items():
        print(f"\\nFetching 30000 candles for {tf_name}...")
        rates = mt5.copy_rates_from_pos(SYMBOL, tf_val, 0, NUM_CANDLES)
        if rates is None or len(rates) == 0: continue
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = calculate_structural_features(df)
        
        print(f"Simulating 10 Structural Strategies on {tf_name} (Spread Penalty = {SPREAD_PIPS} pips)")
        for strat in STRATEGIES:
            res = simulate_strategy(df, strat)
            res['Strategy'] = strat[0]
            res['TF'] = tf_name
            results.append(res)
            
    print("\n============================================================")
    print("                 EURUSD STRUCTURAL MATRIX")
    print("============================================================")
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(by='NetPips', ascending=False)
    print(results_df[['TF', 'Strategy', 'Trades', 'WinRate', 'ProfitFactor', 'NetPips']].to_string(index=False))
    
    best = results_df.iloc[0]
    print("\n============================================================")
    print(f"STRUCTURAL WINNER:")
    print(f"Strategy: {best['Strategy']} on {best['TF']} Chart")
    print(f"Profit Factor: {best['ProfitFactor']}")
    print(f"Net Profit: {best['NetPips']} pips")
    print("============================================================")
    mt5.shutdown()

if __name__ == "__main__":
    main()
