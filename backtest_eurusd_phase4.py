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

def fetch_tf_data(tf_val, num, prefix=""):
    rates = mt5.copy_rates_from_pos(SYMBOL, tf_val, 0, num)
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Calculate MTF indicators before prefixing
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['tick_volume']
    
    df['ema20'] = c.ewm(span=20, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['trend'] = np.where(df['ema20'] > df['ema50'], 1, np.where(df['ema20'] < df['ema50'], -1, 0))
    
    # Elder Ray (Bull/Bear Power)
    df['ema13'] = c.ewm(span=13, adjust=False).mean()
    df['bull_power'] = h - df['ema13']
    df['bear_power'] = l - df['ema13']
    
    # Prefix columns
    if prefix:
        df = df.rename(columns={col: f"{prefix}_{col}" for col in df.columns if col != 'time'})
    return df

def fetch_daily_adr(num):
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, num)
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    tr = pd.concat([df['high'] - df['low'], abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())], axis=1).max(axis=1)
    df['D1_adr14'] = tr.rolling(14).mean()
    
    # We only need the date part to merge properly since daily candles usually sit at 00:00
    df['date'] = df['time'].dt.date
    return df[['date', 'D1_adr14', 'open', 'high', 'low']].rename(columns={'open': 'D1_open', 'high': 'D1_high', 'low': 'D1_low'})

def prepare_data(base_tf_val):
    base_df = fetch_tf_data(base_tf_val, NUM_CANDLES, "")
    if base_df is None: return None
    
    m15_df = fetch_tf_data(mt5.TIMEFRAME_M15, NUM_CANDLES // 3, "M15")
    h1_df = fetch_tf_data(mt5.TIMEFRAME_H1, NUM_CANDLES // 12, "H1")
    h4_df = fetch_tf_data(mt5.TIMEFRAME_H4, NUM_CANDLES // 48, "H4")
    d1_df = fetch_daily_adr(NUM_CANDLES // 288 + 20)
    
    if m15_df is None or h1_df is None or h4_df is None or d1_df is None: return None
    
    # Merge higher timeframes (forward fill the last completed higher timeframe candle)
    # Using merge_asof allows us to join the closest previous higher timeframe candle timestamp
    base_df = pd.merge_asof(base_df, m15_df, on='time', direction='backward')
    base_df = pd.merge_asof(base_df, h1_df, on='time', direction='backward')
    base_df = pd.merge_asof(base_df, h4_df, on='time', direction='backward')
    
    base_df['date'] = base_df['time'].dt.date
    base_df = pd.merge(base_df, d1_df, on='date', how='left')
    
    # Base indicators
    c = base_df['close']
    h = base_df['high']
    l = base_df['low']
    tr = pd.concat([h - l, abs(h - c.shift()), abs(l - c.shift())], axis=1).max(axis=1)
    base_df['atr'] = tr.rolling(14).mean()
    base_df['tr_3bar'] = pd.concat([h.rolling(3).max() - l.rolling(3).min(), abs(h.rolling(3).max() - c.shift(3)), abs(l.rolling(3).min() - c.shift(3))], axis=1).max(axis=1)
    
    # Volume metrics
    base_df['vol_avg'] = base_df['tick_volume'].rolling(20).mean()
    
    base_df['hour'] = base_df['time'].dt.hour
    
    # VWAP (Weekly Anchored)
    base_df['week'] = base_df['time'].dt.isocalendar().week
    base_df['typ_price'] = (h + l + c) / 3
    base_df['typ_vol'] = base_df['typ_price'] * base_df['tick_volume']
    
    # Calculate weekly VWAP
    base_df['cum_vol'] = base_df.groupby('week')['tick_volume'].cumsum()
    base_df['cum_typ_vol'] = base_df.groupby('week')['typ_vol'].cumsum()
    base_df['vwap'] = base_df['cum_typ_vol'] / base_df['cum_vol']
    
    # VWAP StdDev
    # Simplified Variance calculation
    base_df['price_dev_sq'] = ((base_df['typ_price'] - base_df['vwap']) ** 2) * base_df['tick_volume']
    base_df['cum_dev_sq'] = base_df.groupby('week')['price_dev_sq'].cumsum()
    base_df['vwap_variance'] = base_df['cum_dev_sq'] / base_df['cum_vol']
    base_df['vwap_std'] = np.sqrt(base_df['vwap_variance'])
    
    return base_df.dropna().reset_index(drop=True)

# --- 10 Phase 4 Logics ---
# Signal returns: 1 (Long), -1 (Short), 0 (None)

def s1_adr_exhaustion(df, i):
    curr = df.iloc[i]
    today_range = curr['high'] - curr['D1_low'] if curr['close'] > curr['D1_open'] else curr['D1_high'] - curr['low']
    if today_range >= curr['D1_adr14'] * 1.0:
        if curr['close'] > curr['D1_open']: return -1 # Fade the extreme high
        else: return 1 # Fade the extreme low
    return 0

def s2_adr_continuation(df, i):
    curr = df.iloc[i]
    today_range = curr['high'] - curr['D1_low'] if curr['close'] > curr['D1_open'] else curr['D1_high'] - curr['low']
    if today_range > (curr['D1_adr14'] * 0.5) and today_range < (curr['D1_adr14'] * 0.7):
        if curr['close'] > curr['D1_open'] and curr['tick_volume'] > curr['vol_avg'] * 1.5: return 1
        if curr['close'] < curr['D1_open'] and curr['tick_volume'] > curr['vol_avg'] * 1.5: return -1
    return 0

def s3_micro_volatility_spike(df, i):
    curr = df.iloc[i]
    if curr['tr_3bar'] > (curr['atr'] * 3.0):
        if curr['close'] > df.iloc[i-3]['close']: return -1 # Fade massive 3-bar pump
        else: return 1 # Fade massive 3-bar dump
    return 0

def s4_volume_anomaly(df, i):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    # New local high on low volume
    if curr['high'] > df.iloc[i-10:i]['high'].max() and curr['tick_volume'] < curr['vol_avg'] * 0.5:
        return -1
    # New local low on low volume
    if curr['low'] < df.iloc[i-10:i]['low'].min() and curr['tick_volume'] < curr['vol_avg'] * 0.5:
        return 1
    return 0

def s5_time_squeeze(df, i):
    curr = df.iloc[i]
    # Check for extreme compression during Asian session (0-6 UTC)
    if curr['hour'] == 7: # London Open
        asian_range = df.iloc[i-24:i]['high'].max() - df.iloc[i-24:i]['low'].min()
        if asian_range < (curr['D1_adr14'] * 0.3): # Highly compressed
            if curr['close'] > df.iloc[i-24:i]['high'].max(): return 1
            if curr['close'] < df.iloc[i-24:i]['low'].min(): return -1
    return 0

def s6_vwap_std_bounce(df, i):
    curr = df.iloc[i]
    upper_band = curr['vwap'] + (curr['vwap_std'] * 2.0)
    lower_band = curr['vwap'] - (curr['vwap_std'] * 2.0)
    if curr['high'] >= upper_band and curr['close'] < upper_band: return -1
    if curr['low'] <= lower_band and curr['close'] > lower_band: return 1
    return 0

def s7_triple_screen(df, i):
    curr = df.iloc[i]
    if curr['H4_trend'] == 1 and curr['H1_trend'] == 1 and curr['M15_trend'] == 1:
        if curr['close'] < curr['ema20'] and curr['close'] > curr['ema50']: return 1
    if curr['H4_trend'] == -1 and curr['H1_trend'] == -1 and curr['M15_trend'] == -1:
        if curr['close'] > curr['ema20'] and curr['close'] < curr['ema50']: return -1
    return 0

def s8_elder_ray_mtf(df, i):
    curr = df.iloc[i]
    if curr['H1_bull_power'] > 0 and curr['H1_bear_power'] > 0:
        if curr['bear_power'] < 0 and curr['bull_power'] > 0: return 1
    if curr['H1_bull_power'] < 0 and curr['H1_bear_power'] < 0:
        if curr['bull_power'] > 0 and curr['bear_power'] < 0: return -1
    return 0

def s9_orb_vol_conf(df, i):
    curr = df.iloc[i]
    if curr['hour'] == 8 or curr['hour'] == 9:
        london_high = df.iloc[i-12:i]['high'].max() # Approx first hour
        london_low = df.iloc[i-12:i]['low'].min()
        if curr['close'] > london_high and curr['tick_volume'] > curr['vol_avg'] * 2.0: return 1
        if curr['close'] < london_low and curr['tick_volume'] > curr['vol_avg'] * 2.0: return -1
    return 0

def s10_perfect_storm(df, i):
    curr = df.iloc[i]
    if curr['H4_trend'] == 1 and curr['close'] > curr['M15_high'] and curr['tick_volume'] > curr['vol_avg'] * 1.5:
        return 1
    if curr['H4_trend'] == -1 and curr['close'] < curr['M15_low'] and curr['tick_volume'] > curr['vol_avg'] * 1.5:
        return -1
    return 0

STRATEGIES = [
    ("1_ADR_Exhaustion", s1_adr_exhaustion, 1.0, 2.0),
    ("2_ADR_Continuation", s2_adr_continuation, 1.0, 2.0),
    ("3_MicroVol_SpikeFade", s3_micro_volatility_spike, 1.5, 2.5),
    ("4_Vol_Anomaly_Divergence", s4_volume_anomaly, 1.0, 2.0),
    ("5_Time_Volatility_Squeeze", s5_time_squeeze, 1.5, 2.0),
    ("6_VWAP_Bands", s6_vwap_std_bounce, 1.0, 2.0),
    ("7_Triple_Screen", s7_triple_screen, 1.0, 2.0),
    ("8_Elder_Ray_MTF", s8_elder_ray_mtf, 1.0, 1.5),
    ("9_ORB_VolConf", s9_orb_vol_conf, 1.0, 2.0),
    ("10_Perfect_Storm", s10_perfect_storm, 1.5, 3.0)
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
    
    for i in range(50, len(df)):
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
            
        try:
            signal = logic_func(df, i-1)
        except Exception:
            continue
            
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
    }
    
    results = []
    
    for tf_name, tf_val in timeframes.items():
        print(f"\\nFetching MTF data centered around {tf_name}...")
        df = prepare_data(tf_val)
        if df is None:
            print(f"Failed to prepare data for {tf_name}")
            continue
            
        print(f"Simulating 10 Phase 4 Strategies on {tf_name} (Spread Penalty = {SPREAD_PIPS} pips)")
        for strat in STRATEGIES:
            res = simulate_strategy(df, strat)
            res['Strategy'] = strat[0]
            res['TF'] = tf_name
            results.append(res)
            
    print("\n============================================================")
    print("                 EURUSD PHASE 4 MATRIX")
    print("============================================================")
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(by='NetPips', ascending=False)
    print(results_df[['TF', 'Strategy', 'Trades', 'WinRate', 'ProfitFactor', 'NetPips']].to_string(index=False))
    
    best = results_df.iloc[0]
    print("\n============================================================")
    print(f"PHASE 4 WINNER:")
    print(f"Strategy: {best['Strategy']} on {best['TF']} Chart")
    print(f"Profit Factor: {best['ProfitFactor']}")
    print(f"Net Profit: {best['NetPips']} pips")
    print("============================================================")
    mt5.shutdown()

if __name__ == "__main__":
    main()
