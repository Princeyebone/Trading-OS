"""
backtest_sl.py
Tests the proposed Triple-Layer Stop Loss system for Momentum Scalps.
Compares Baseline (10pt SL, no time limit) vs New System:
 1. Time Stop: Exit if not +1pt profit within 3 M5 candles.
 2. Structure SL: SL at previous candle's low/high +/- 0.5pt buffer.
 3. Hard Cap: Skip trade if Structure SL is > 5pts away.
"""

import sys, os
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

# ─── Config ──────────────────────────────────────────────────────────────────
GAP_TOL  =  0.09
TP1_PTS  =  5.0
BUFFER   =  0.5
MAX_RISK =  5.0
TIME_LIMIT = 3   # 3 candles = 15 mins
LOCK_REQ   = 1.0 # Need 1pt profit to avoid time stop

def fetch_data():
    if not mt5.initialize():
        raise RuntimeError("MT5 init failed")
    m5_rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 50000)
    m5 = pd.DataFrame(m5_rates)
    m5["time"] = pd.to_datetime(m5["time"], unit="s", utc=True)
    m5.set_index("time", inplace=True)
    return m5

def simulate_baseline(m5, entry_idx, direction):
    """Old system: fixed 10pt SL, wait 48 candles max."""
    entry = float(m5["open"].iloc[entry_idx])
    sl_pts = 10.0
    sl_price = entry - sl_pts if direction == "BULLISH" else entry + sl_pts
    tp_price = entry + TP1_PTS if direction == "BULLISH" else entry - TP1_PTS

    exit_pts = None
    candles = 0

    for i in range(entry_idx + 1, min(entry_idx + 49, len(m5))):
        row = m5.iloc[i]
        h, l = float(row["high"]), float(row["low"])
        candles += 1

        if direction == "BULLISH":
            if l <= sl_price: return -sl_pts, candles, "SL"
            if h >= tp_price: return TP1_PTS, candles, "TP"
        else:
            if h >= sl_price: return -sl_pts, candles, "SL"
            if l <= tp_price: return TP1_PTS, candles, "TP"

    # Timeout exit
    c = float(m5["close"].iloc[min(entry_idx + 48, len(m5) - 1)])
    return (c - entry if direction == "BULLISH" else entry - c), candles, "TIMEOUT"


def simulate_new_sl(m5, entry_idx, direction):
    """
    New system:
    - SL = prev candle low/high + buffer
    - Abort if SL distance > 5.0
    - Time Stop: exit at close of candle 3 if max favorable excursion < 1.0 pt
    """
    entry = float(m5["open"].iloc[entry_idx])
    prev_h = float(m5["high"].iloc[entry_idx - 1])
    prev_l = float(m5["low"].iloc[entry_idx - 1])

    if direction == "BULLISH":
        sl_price = prev_l - BUFFER
        sl_dist = entry - sl_price
    else:
        sl_price = prev_h + BUFFER
        sl_dist = sl_price - entry

    # Hard Cap
    if sl_dist > MAX_RISK:
        return 0.0, 0, "ABORTED_RISK_TOO_HIGH"

    tp_price = entry + TP1_PTS if direction == "BULLISH" else entry - TP1_PTS
    max_favorable = 0.0

    candles = 0
    for i in range(entry_idx + 1, min(entry_idx + 49, len(m5))):
        row = m5.iloc[i]
        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
        candles += 1

        if direction == "BULLISH":
            fav = h - entry
            max_favorable = max(max_favorable, fav)
            if l <= sl_price: return -sl_dist, candles, "STRUCT_SL"
            if h >= tp_price: return TP1_PTS, candles, "TP"
        else:
            fav = entry - l
            max_favorable = max(max_favorable, fav)
            if h >= sl_price: return -sl_dist, candles, "STRUCT_SL"
            if l <= tp_price: return TP1_PTS, candles, "TP"

        # Time stop check at candle 3
        if candles == TIME_LIMIT and max_favorable < LOCK_REQ:
            exit_pts = c - entry if direction == "BULLISH" else entry - c
            return exit_pts, candles, "TIME_STOP"

    c = float(m5["close"].iloc[min(entry_idx + 48, len(m5) - 1)])
    return (c - entry if direction == "BULLISH" else entry - c), candles, "TIMEOUT"


def run():
    print("Fetching 50,000 M5 bars...")
    m5 = fetch_data()
    
    records = []
    
    for i in range(10, len(m5) - 50):
        curr_o = float(m5["open"].iloc[i])
        curr_c = float(m5["close"].iloc[i])
        prev_o = float(m5["open"].iloc[i-1])
        prev_c = float(m5["close"].iloc[i-1])

        prev_bearish = prev_c < prev_o
        prev_bullish = prev_c > prev_o

        crown = prev_bullish and (curr_o >= prev_c - GAP_TOL)
        base  = prev_bearish and (curr_o <= prev_c + GAP_TOL)

        if not crown and not base:
            continue
            
        direction = "BULLISH" if crown else "BEARISH"
        
        b_pnl, b_cand, b_reas = simulate_baseline(m5, i, direction)
        n_pnl, n_cand, n_reas = simulate_new_sl(m5, i, direction)
        
        records.append({
            "setup": "CROWN" if crown else "BASE",
            "direction": direction,
            "base_pnl": b_pnl,
            "base_reason": b_reas,
            "new_pnl": n_pnl,
            "new_reason": n_reas,
        })
        
    df = pd.DataFrame(records)
    print(f"Signals analysed: {len(df)}")
    
    # Analyze
    print("\n" + "="*60)
    print("BASELINE (10pt Fixed SL) vs TRIPLE-LAYER SL (5pt Max, Time Stop)")
    print("="*60)
    
    total_trades = len(df)
    
    # Baseline stats
    b_wins = df[df["base_pnl"] >= TP1_PTS]
    b_losses = df[df["base_pnl"] <= -5.0]  # count big losses
    b_win_rate = len(b_wins) / total_trades * 100
    b_net = df["base_pnl"].sum()
    
    # New Stats
    # Remove aborted trades from the pool
    taken_trades = df[df["new_reason"] != "ABORTED_RISK_TOO_HIGH"]
    aborted = len(df) - len(taken_trades)
    
    if len(taken_trades) > 0:
        n_wins = taken_trades[taken_trades["new_pnl"] >= TP1_PTS]
        n_win_rate = len(n_wins) / len(taken_trades) * 100
        n_net = taken_trades["new_pnl"].sum()
        
        time_stops = taken_trades[taken_trades["new_reason"] == "TIME_STOP"]
        struct_sls = taken_trades[taken_trades["new_reason"] == "STRUCT_SL"]
        
        avg_loss = taken_trades[taken_trades["new_pnl"] < 0]["new_pnl"].mean()
        avg_base_loss = df[df["base_pnl"] < 0]["base_pnl"].mean()
        
        print(f"\n[ABORT FILTER]")
        print(f"Total Signals Fired: {total_trades}")
        print(f"Aborted (Risk > 5pts): {aborted} ({(aborted/total_trades)*100:.1f}%)")
        print(f"Trades Taken: {len(taken_trades)}")
        
        print(f"\n[WIN RATE @ +5pts]")
        print(f"Baseline: {b_win_rate:.1f}%")
        print(f"New SL  : {n_win_rate:.1f}%")
        
        print(f"\n[NET PROFIT (Points)]")
        print(f"Baseline: {b_net:+.1f} pts")
        print(f"New SL  : {n_net:+.1f} pts")
        
        print(f"\n[LOSS PROTECTION]")
        print(f"Baseline Avg Loss: {avg_base_loss:.2f} pts")
        print(f"New SL Avg Loss  : {avg_loss:.2f} pts")
        
        print(f"\n[NEW EXIT REASONS (Trades Taken)]")
        print(f"Hit +5pt TP : {len(n_wins)}")
        print(f"Time Stopped: {len(time_stops)} (Avg PnL: {time_stops['new_pnl'].mean():.2f} pts)")
        print(f"Struct SL   : {len(struct_sls)} (Avg PnL: {struct_sls['new_pnl'].mean():.2f} pts)")
    
if __name__ == "__main__":
    run()
