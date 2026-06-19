"""
backtest_filtered.py
Tests 5.0pt SL / 5.0pt TP with Trend Filtering.
"""

import sys, os
import MetaTrader5 as mt5
import pandas as pd
import ta

TP_PTS = 5.0
SL_PTS = 5.0
GAP_TOL = 0.09

def fetch_data():
    if not mt5.initialize():
        raise RuntimeError("MT5 init failed")
    m5_rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 50000)
    h1_rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 10000)
    h4_rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H4, 0, 3000)

    m5 = pd.DataFrame(m5_rates)
    h1 = pd.DataFrame(h1_rates)
    h4 = pd.DataFrame(h4_rates)

    for df in (m5, h1, h4):
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df["ema_20"] = ta.trend.ema_indicator(df["close"], window=20)
        df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)

    return m5, h1, h4

def get_trend(df, ts):
    past = df[df.index <= ts]
    if len(past) < 50: return "MIXED"
    row = past.iloc[-1]
    if row["ema_20"] > row["ema_50"]: return "BULLISH"
    if row["ema_20"] < row["ema_50"]: return "BEARISH"
    return "MIXED"

def simulate_fixed_sl(m5, entry_idx, direction):
    entry = float(m5["open"].iloc[entry_idx])
    sl_price = entry - SL_PTS if direction == "BULLISH" else entry + SL_PTS
    tp_price = entry + TP_PTS if direction == "BULLISH" else entry - TP_PTS

    for i in range(entry_idx + 1, min(entry_idx + 49, len(m5))):
        row = m5.iloc[i]
        h, l = float(row["high"]), float(row["low"])

        if direction == "BULLISH":
            if l <= sl_price: return -SL_PTS
            if h >= tp_price: return TP_PTS
        else:
            if h >= sl_price: return -SL_PTS
            if l <= tp_price: return TP_PTS

    c = float(m5["close"].iloc[min(entry_idx + 48, len(m5) - 1)])
    return c - entry if direction == "BULLISH" else entry - c

def run():
    print("Fetching data...")
    m5, h1, h4 = fetch_data()
    
    unfiltered = []
    h4_filtered = []
    h4_h1_filtered = []
    
    print("Scanning...")
    for i in range(10, len(m5) - 50):
        curr_o = float(m5["open"].iloc[i])
        curr_c = float(m5["close"].iloc[i])
        prev_o = float(m5["open"].iloc[i-1])
        prev_c = float(m5["close"].iloc[i-1])

        crown = (prev_c > prev_o) and (curr_o >= prev_c - GAP_TOL)
        base  = (prev_c < prev_o) and (curr_o <= prev_c + GAP_TOL)

        if not crown and not base:
            continue
            
        direction = "BULLISH" if crown else "BEARISH"
        ts = m5.index[i]
        
        # Determine trends
        h4_tr = get_trend(h4, ts)
        h1_tr = get_trend(h1, ts)
        
        pnl = simulate_fixed_sl(m5, i, direction)
        
        # All signals
        unfiltered.append(pnl)
        
        # H4 filtered
        if direction == "BULLISH" and h4_tr == "BULLISH":
            h4_filtered.append(pnl)
        elif direction == "BEARISH" and h4_tr == "BEARISH":
            h4_filtered.append(pnl)
            
        # H4 + H1 filtered
        if direction == "BULLISH" and h4_tr == "BULLISH" and h1_tr == "BULLISH":
            h4_h1_filtered.append(pnl)
        elif direction == "BEARISH" and h4_tr == "BEARISH" and h1_tr == "BEARISH":
            h4_h1_filtered.append(pnl)

    # Print results
    def print_stats(name, res):
        n = len(res)
        if n == 0: return
        wins = sum(1 for p in res if p >= TP_PTS)
        net = sum(res)
        wr = (wins / n) * 100
        print(f"{name:<25} | n={n:<5} | WR: {wr:>5.1f}% | Net: {net:+.1f} pts")

    print("\n" + "="*70)
    print("  TEST: 5.0pt Stop Loss | 5.0pt Take Profit (1:1 Risk/Reward)")
    print("="*70)
    print_stats("1. Unfiltered (Take All)", unfiltered)
    print_stats("2. H4 Trend Filter Only", h4_filtered)
    print_stats("3. H4 + H1 Dual Filter", h4_h1_filtered)
    print("="*70 + "\n")

if __name__ == "__main__":
    run()
