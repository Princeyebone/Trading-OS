import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import os
import time

MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "0"))
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")
SYMBOL = "EURUSD"
SPREAD_PIPS = 1.0
NUM_CANDLES = 30000

def _init_mt5():
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        return False
    return True

def calculate_phase3_features(df):
    c = df['close']
    h = df['high']
    l = df['low']
    o = df['open']
    v = df['tick_volume']
    
    # Time basics
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    df['day_of_week'] = df['time'].dt.dayofweek # 0=Mon, 4=Fri
    
    # 1. ATR (14)
    tr = pd.concat([h - l, abs(h - c.shift()), abs(l - c.shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['tr'] = tr
    
    # 2. V-MACD (Volume Weighted MACD)
    vol_price = c * v
    vw_ema12 = vol_price.rolling(12).sum() / v.rolling(12).sum()
    vw_ema26 = vol_price.rolling(26).sum() / v.rolling(26).sum()
    df['vmacd'] = vw_ema12 - vw_ema26
    df['vmacd_signal'] = df['vmacd'].rolling(9).mean()
    
    # 3. Inside Bar & Hikkake
    df['inside_bar'] = (h < h.shift(1)) & (l > l.shift(1))
    
    # 4. Initial Balance (NY 13:00 to 14:00)
    ib_mask = (df['hour'] >= 13) & (df['hour'] < 14)
    df['ib_high'] = df.loc[ib_mask].groupby('date')['high'].transform('max')
    df['ib_low'] = df.loc[ib_mask].groupby('date')['low'].transform('min')
    df['ib_high'] = df.groupby('date')['ib_high'].ffill().bfill()
    df['ib_low'] = df.groupby('date')['ib_low'].ffill().bfill()
    
    # 5. Previous Day Extreme
    df['prev_high'] = df.groupby('date')['high'].transform('max').shift(1)
    df['prev_low'] = df.groupby('date')['low'].transform('min').shift(1)
    
    # 6. Weekly Gap (Friday close vs Monday open)
    df['is_monday'] = df['day_of_week'] == 0
    # Find gaps > 1 ATR on Monday open
    df['gap_up'] = (df['is_monday']) & (df['open'] > c.shift(1) + df['atr'].shift(1))
    df['gap_down'] = (df['is_monday']) & (df['open'] < c.shift(1) - df['atr'].shift(1))
    
    # 7. Smoothed Heikin-Ashi (Smoothed by SMA 6)
    ha_close = (o + h + l + c) / 4
    ha_open = (o.shift(1) + c.shift(1)) / 2
    df['ha_c_smooth'] = ha_close.rolling(6).mean()
    df['ha_o_smooth'] = ha_open.rolling(6).mean()
    
    # 8. Fractals (Bill Williams)
    df['fractal_up'] = (h > h.shift(1)) & (h > h.shift(2)) & (h > h.shift(-1)) & (h > h.shift(-2))
    df['fractal_down'] = (l < l.shift(1)) & (l < l.shift(2)) & (l < l.shift(-1)) & (l < l.shift(-2))
    df['last_frac_up'] = df['high'].where(df['fractal_up']).ffill()
    df['last_frac_dn'] = df['low'].where(df['fractal_down']).ffill()
    
    # 9. Triple EMA
    df['ema8'] = c.ewm(span=8, adjust=False).mean()
    df['ema13'] = c.ewm(span=13, adjust=False).mean()
    df['ema21'] = c.ewm(span=21, adjust=False).mean()
    
    return df.dropna().reset_index(drop=True)


# --- 10 Phase 3 Logics ---
# Signal returns: 1 (Long), -1 (Short), 0 (None)

def s1_london_fix_reversal(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    if curr['hour'] == 16: # London Fix
        # Fade the momentum of the 16:00 candle
        if curr['close'] > prev['close'] + curr['atr']: return -1
        if curr['close'] < prev['close'] - curr['atr']: return 1
    return 0

def s2_vmacd_cross(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    # Cross UP
    if prev['vmacd'] < prev['vmacd_signal'] and curr['vmacd'] > curr['vmacd_signal']:
        if curr['vmacd'] < 0: return 1 # Cross below zero line
    # Cross DOWN
    if prev['vmacd'] > prev['vmacd_signal'] and curr['vmacd'] < curr['vmacd_signal']:
        if curr['vmacd'] > 0: return -1
    return 0

def s3_momentum_expansion(df, i):
    curr = df.iloc[i]
    if curr['tr'] > (3 * curr['atr']):
        if curr['close'] > curr['open']: return 1
        else: return -1
    return 0

def s4_hikkake(df, i):
    curr = df.iloc[i]
    # Look back 3 bars for an inside bar
    for j in range(1, 4):
        if df.iloc[i-j]['inside_bar']:
            inside = df.iloc[i-j]
            # Fakeout Up, now breaking Down
            if df.iloc[i-1]['high'] > inside['high'] and curr['close'] < inside['low']:
                return -1
            # Fakeout Down, now breaking Up
            if df.iloc[i-1]['low'] < inside['low'] and curr['close'] > inside['high']:
                return 1
    return 0

def s5_ib_breakout(df, i):
    curr = df.iloc[i]
    if curr['hour'] >= 14 and curr['hour'] < 18:
        if curr['close'] > curr['ib_high']: return 1
        if curr['close'] < curr['ib_low']: return -1
    return 0

def s6_prev_day_extreme(df, i):
    curr = df.iloc[i]
    if curr['close'] > curr['prev_high']: return 1
    if curr['close'] < curr['prev_low']: return -1
    return 0

def s7_weekly_gap_close(df, i):
    curr = df.iloc[i]
    if curr['gap_up']: return -1 # Fade the gap UP
    if curr['gap_down']: return 1 # Fade the gap DOWN
    return 0

def s8_ha_smoothed(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    if prev['ha_c_smooth'] <= prev['ha_o_smooth'] and curr['ha_c_smooth'] > curr['ha_o_smooth']:
        return 1
    if prev['ha_c_smooth'] >= prev['ha_o_smooth'] and curr['ha_c_smooth'] < curr['ha_o_smooth']:
        return -1
    return 0

def s9_fractal_reversal(df, i):
    curr = df.iloc[i]
    if curr['high'] > curr['last_frac_up'] and curr['close'] < curr['last_frac_up']: return -1
    if curr['low'] < curr['last_frac_dn'] and curr['close'] > curr['last_frac_dn']: return 1
    return 0

def s10_triple_ema_ribbon(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    # Bullish Fan
    if curr['ema8'] > curr['ema13'] > curr['ema21']:
        if prev['low'] < curr['ema8'] and curr['close'] > curr['ema8']: return 1
    # Bearish Fan
    if curr['ema8'] < curr['ema13'] < curr['ema21']:
        if prev['high'] > curr['ema8'] and curr['close'] < curr['ema8']: return -1
    return 0

STRATEGIES = [
    ("1_London_Fix_Fade", s1_london_fix_reversal, 1.0, 2.0),
    ("2_VMACD_Cross", s2_vmacd_cross, 1.5, 2.0),
    ("3_Momentum_Expansion", s3_momentum_expansion, 1.5, 3.0),
    ("4_Hikkake_Fakeout", s4_hikkake, 1.0, 2.0),
    ("5_IB_Breakout", s5_ib_breakout, 1.0, 1.5),
    ("6_PrevDay_Breakout", s6_prev_day_extreme, 1.5, 2.0),
    ("7_Weekly_Gap_Close", s7_weekly_gap_close, 2.0, 2.0),
    ("8_HA_Smoothed", s8_ha_smoothed, 1.5, 2.0),
    ("9_Fractal_Reversal", s9_fractal_reversal, 1.0, 2.0),
    ("10_Triple_EMA", s10_triple_ema_ribbon, 1.5, 2.0)
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
    
    # Precompute signals to save time? Actually logic_func is fast enough
    for i in range(10, len(df)):
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
        df = calculate_phase3_features(df)
        
        print(f"Simulating 10 Phase 3 Strategies on {tf_name} (Spread Penalty = {SPREAD_PIPS} pips)")
        for strat in STRATEGIES:
            res = simulate_strategy(df, strat)
            res['Strategy'] = strat[0]
            res['TF'] = tf_name
            results.append(res)
            
    print("\n============================================================")
    print("                 EURUSD PHASE 3 MATRIX")
    print("============================================================")
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(by='NetPips', ascending=False)
    print(results_df[['TF', 'Strategy', 'Trades', 'WinRate', 'ProfitFactor', 'NetPips']].to_string(index=False))
    
    best = results_df.iloc[0]
    print("\n============================================================")
    print(f"PHASE 3 WINNER:")
    print(f"Strategy: {best['Strategy']} on {best['TF']} Chart")
    print(f"Profit Factor: {best['ProfitFactor']}")
    print(f"Net Profit: {best['NetPips']} pips")
    print("============================================================")
    mt5.shutdown()

if __name__ == "__main__":
    main()
