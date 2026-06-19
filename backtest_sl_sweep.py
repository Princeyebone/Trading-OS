"""
backtest_sl_sweep.py
Tests different fixed Stop Loss levels (from 3pt to 9pt) to find the optimal 
balance between high win-rate and downside protection.
TP is fixed at +5.0 pts.
"""

import sys, os
import MetaTrader5 as mt5
import pandas as pd

TP_PTS = 5.0
SL_TESTS = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
GAP_TOL = 0.09

def fetch_data():
    if not mt5.initialize():
        raise RuntimeError("MT5 init failed")
    m5_rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 50000)
    m5 = pd.DataFrame(m5_rates)
    m5["time"] = pd.to_datetime(m5["time"], unit="s", utc=True)
    m5.set_index("time", inplace=True)
    return m5

def simulate_fixed_sl(m5, entry_idx, direction, sl_pts):
    entry = float(m5["open"].iloc[entry_idx])
    sl_price = entry - sl_pts if direction == "BULLISH" else entry + sl_pts
    tp_price = entry + TP_PTS if direction == "BULLISH" else entry - TP_PTS

    for i in range(entry_idx + 1, min(entry_idx + 49, len(m5))):
        row = m5.iloc[i]
        h, l = float(row["high"]), float(row["low"])

        if direction == "BULLISH":
            if l <= sl_price: return -sl_pts
            if h >= tp_price: return TP_PTS
        else:
            if h >= sl_price: return -sl_pts
            if l <= tp_price: return TP_PTS

    c = float(m5["close"].iloc[min(entry_idx + 48, len(m5) - 1)])
    return c - entry if direction == "BULLISH" else entry - c

def run():
    print("Fetching 50,000 M5 bars...")
    m5 = fetch_data()
    
    # Store signals
    signals = []
    for i in range(10, len(m5) - 50):
        curr_o = float(m5["open"].iloc[i])
        curr_c = float(m5["close"].iloc[i])
        prev_o = float(m5["open"].iloc[i-1])
        prev_c = float(m5["close"].iloc[i-1])

        crown = (prev_c > prev_o) and (curr_o >= prev_c - GAP_TOL)
        base  = (prev_c < prev_o) and (curr_o <= prev_c + GAP_TOL)

        if crown: signals.append((i, "BULLISH"))
        elif base: signals.append((i, "BEARISH"))

    print(f"Signals found: {len(signals)}")
    print("\n" + "="*70)
    print(f"{'SL Level':<10} | {'Win Rate':<10} | {'Total Profit':<15} | {'Avg Loss':<10}")
    print("="*70)

    for sl_pts in SL_TESTS:
        wins, losses = 0, 0
        net_profit = 0.0
        
        for idx, direction in signals:
            pnl = simulate_fixed_sl(m5, idx, direction, sl_pts)
            net_profit += pnl
            if pnl >= TP_PTS:
                wins += 1
            elif pnl <= -sl_pts:
                losses += 1
                
        total = len(signals)
        win_rate = (wins / total) * 100
        avg_loss = -sl_pts
        
        print(f"SL {sl_pts:<4.1f} pt | {win_rate:>5.1f}%     | {net_profit:>10.1f} pts  | {avg_loss:>5.1f} pts")

if __name__ == "__main__":
    run()
