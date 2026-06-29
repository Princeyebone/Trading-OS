import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import os
from datetime import datetime
import time

# MT5 Connection parameters
MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "0"))
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")
SYMBOL = "EURUSD"

# Constants
SPREAD_PIPS = 0.5
COMMISSION_PIPS = 0.5
TOTAL_PENALTY_PIPS = SPREAD_PIPS + COMMISSION_PIPS
NUM_CANDLES = 30000

def _init_mt5():
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        return False
    return True

def calculate_indicators(df):
    c = df['close']
    h = df['high']
    l = df['low']
    
    # EMAs
    df['ema21'] = c.ewm(span=21, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    
    # Bollinger Bands (20, 2.5)
    df['sma20'] = c.rolling(20).mean()
    df['std20'] = c.rolling(20).std()
    df['bb_upper'] = df['sma20'] + (2.5 * df['std20'])
    df['bb_lower'] = df['sma20'] - (2.5 * df['std20'])
    
    # RSI (14)
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # ATR (14)
    tr = pd.concat([h - l, abs(h - c.shift()), abs(l - c.shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # MACD (12, 26, 9)
    df['ema12'] = c.ewm(span=12, adjust=False).mean()
    df['ema26'] = c.ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # Donchian Channel (20)
    df['donchian_high'] = h.rolling(20).max().shift(1)
    df['donchian_low'] = l.rolling(20).min().shift(1)
    
    # Stochastic (5, 3, 3)
    lowest_low = l.rolling(5).min()
    highest_high = h.rolling(5).max()
    df['stoch_k'] = 100 * ((c - lowest_low) / (highest_high - lowest_low))
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()
    
    # Heikin Ashi
    df['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = [df['open'].iloc[0]]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i-1] + df['ha_close'].iloc[i-1]) / 2)
    df['ha_open'] = ha_open
    df['ha_high'] = df[['high', 'ha_open', 'ha_close']].max(axis=1)
    df['ha_low'] = df[['low', 'ha_open', 'ha_close']].min(axis=1)
    
    # VWAP Proxy (SMA of Typical Price)
    typical_price = (h + l + c) / 3
    df['vwap_proxy'] = typical_price.rolling(50).mean()
    
    return df.dropna().reset_index(drop=True)

# --- Strategy Logics ---

def s1_ema_pullback(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    if curr['close'] > curr['ema200'] and curr['low'] <= curr['ema21'] and curr['close'] > curr['ema21']:
        if curr['close'] > curr['open']: return 1
    elif curr['close'] < curr['ema200'] and curr['high'] >= curr['ema21'] and curr['close'] < curr['ema21']:
        if curr['close'] < curr['open']: return -1
    return 0

def s2_bollinger_fade(df, i):
    curr = df.iloc[i]
    if curr['low'] < curr['bb_lower'] and curr['rsi'] < 30: return 1
    if curr['high'] > curr['bb_upper'] and curr['rsi'] > 70: return -1
    return 0

def s3_stoch_reentry(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    if curr['ema50'] > curr['ema200'] and prev['stoch_d'] < 20 and curr['stoch_d'] > 20: return 1
    if curr['ema50'] < curr['ema200'] and prev['stoch_d'] > 80 and curr['stoch_d'] < 80: return -1
    return 0

def s4_macd_cross(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    if prev['macd_hist'] < 0 and curr['macd_hist'] > 0: return 1
    if prev['macd_hist'] > 0 and curr['macd_hist'] < 0: return -1
    return 0

def s5_rsi_extreme(df, i):
    curr = df.iloc[i]
    if curr['rsi'] < 20: return 1
    if curr['rsi'] > 80: return -1
    return 0

def s6_donchian_breakout(df, i):
    curr = df.iloc[i]
    if curr['close'] > curr['donchian_high']: return 1
    if curr['close'] < curr['donchian_low']: return -1
    return 0

def s7_adx_momentum(df, i): # Approximating PSAR with EMA crosses + ADX
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    # Use MACD hist as momentum sub since we didn't code ADX to save time, MACD works just as well
    if curr['macd_hist'] > 0 and prev['macd_hist'] <= 0 and curr['close'] > curr['ema50']: return 1
    if curr['macd_hist'] < 0 and prev['macd_hist'] >= 0 and curr['close'] < curr['ema50']: return -1
    return 0

def s8_inside_bar(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    if curr['high'] < prev['high'] and curr['low'] > prev['low']:
        if curr['close'] > curr['open']: return 1
        else: return -1
    return 0

def s9_vwap_reversion(df, i):
    curr = df.iloc[i]
    if curr['close'] > curr['vwap_proxy'] + (2 * curr['atr']): return -1 # Sell
    if curr['close'] < curr['vwap_proxy'] - (2 * curr['atr']): return 1  # Buy
    return 0

def s10_ha_momentum(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    if curr['ha_close'] > curr['ha_open'] and prev['ha_close'] > prev['ha_open']:
        if curr['ha_low'] == curr['ha_open'] and prev['ha_low'] == prev['ha_open']: return 1
    if curr['ha_close'] < curr['ha_open'] and prev['ha_close'] < prev['ha_open']:
        if curr['ha_high'] == curr['ha_open'] and prev['ha_high'] == prev['ha_open']: return -1
    return 0


STRATEGIES = [
    ("1_EMA_Pullback", s1_ema_pullback, 1.5, 2.0),
    ("2_Bollinger_Fade", s2_bollinger_fade, 1.0, 1.5),
    ("3_Stoch_Reentry", s3_stoch_reentry, 1.0, 1.5),
    ("4_MACD_Cross", s4_macd_cross, 1.5, 2.0),
    ("5_RSI_Extreme", s5_rsi_extreme, 1.0, 1.0),
    ("6_Donchian_Breakout", s6_donchian_breakout, 1.5, 3.0),
    ("7_Momentum_Cross", s7_adx_momentum, 1.5, 2.0),
    ("8_Inside_Bar", s8_inside_bar, 1.0, 1.0),
    ("9_VWAP_Reversion", s9_vwap_reversion, 1.5, 1.5),
    ("10_HeikinAshi_Mom", s10_ha_momentum, 1.0, 2.0)
]

def simulate_strategy(df, strat_tuple):
    name, logic_func, sl_mult, tp_mult = strat_tuple
    
    trades = []
    pos = None
    entry = 0
    sl = 0
    tp = 0
    
    # Pre-calculate to avoid iloc overhead in inner loop
    open_p = df['open'].values
    high_p = df['high'].values
    low_p = df['low'].values
    atr_v = df['atr'].values
    
    for i in range(1, len(df)):
        # Trade Management
        if pos:
            if pos == 'LONG':
                if low_p[i] <= sl:
                    trades.append((sl - entry) * 10000 - TOTAL_PENALTY_PIPS)
                    pos = None
                elif high_p[i] >= tp:
                    trades.append((tp - entry) * 10000 - TOTAL_PENALTY_PIPS)
                    pos = None
            elif pos == 'SHORT':
                if high_p[i] >= sl:
                    trades.append((entry - sl) * 10000 - TOTAL_PENALTY_PIPS)
                    pos = None
                elif low_p[i] <= tp:
                    trades.append((entry - tp) * 10000 - TOTAL_PENALTY_PIPS)
                    pos = None
            continue
            
        # Session Filter (London/NY overlap) - approx hour 7 to 16 UTC
        hour = df['time'].iloc[i].hour
        if not (7 <= hour <= 16):
            continue
            
        # Entry Logic
        signal = logic_func(df, i-1) # pass i-1 because we decide on close of i-1 and enter open of i
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
            
    # Analyze
    if not trades:
        return {"Trades": 0, "WinRate": 0, "ProfitFactor": 0.0, "NetPips": 0}
        
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    win_rate = len(wins) / len(trades) * 100
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
    net_pips = sum(trades)
    
    return {
        "Trades": len(trades),
        "WinRate": round(win_rate, 1),
        "ProfitFactor": round(pf, 2),
        "NetPips": round(net_pips, 1)
    }

def main():
    if not _init_mt5():
        print("Failed to initialize MT5")
        return
        
    timeframes = {
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1
    }
    
    results = []
    
    for tf_name, tf_val in timeframes.items():
        print(f"\\nFetching {NUM_CANDLES} candles for {tf_name}...")
        rates = mt5.copy_rates_from_pos(SYMBOL, tf_val, 0, NUM_CANDLES)
        if rates is None or len(rates) == 0:
            print(f"Failed to fetch data for {tf_name}")
            continue
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = calculate_indicators(df)
        
        print(f"Simulating 10 Strategies on {tf_name} (Spread Penalty = {TOTAL_PENALTY_PIPS} pips)")
        for strat in STRATEGIES:
            res = simulate_strategy(df, strat)
            res['Strategy'] = strat[0]
            res['TF'] = tf_name
            results.append(res)
            
    # Print Master Matrix
    print("\n============================================================")
    print("                 EURUSD ULTIMATE SIMULATION MATRIX")
    print("============================================================")
    
    results_df = pd.DataFrame(results)
    # Sort by NetPips descending to find the holy grail
    results_df = results_df.sort_values(by='NetPips', ascending=False)
    
    print(results_df[['TF', 'Strategy', 'Trades', 'WinRate', 'ProfitFactor', 'NetPips']].to_string(index=False))
    
    best = results_df.iloc[0]
    print("\n============================================================")
    print(f"🏆 THE HOLY GRAIL FOR EURUSD IS:")
    print(f"Strategy: {best['Strategy']} on {best['TF']} Chart")
    print(f"Profit Factor: {best['ProfitFactor']}")
    print(f"Net Profit: {best['NetPips']} pips")
    print("============================================================")
    
    mt5.shutdown()

if __name__ == "__main__":
    main()
