"""
backtest_momentum.py
Backtest Crown Momentum (BUY) and Base Momentum (SELL) setups
against 9 months of XAUUSD M5 data.

For each signal, simulate:
  - SL: -10 pts from entry
  - TP targets: +5, +10, +15 pts from entry

Segments results by H4 trend, H1 trend, session, ATR regime,
prev candle size, and EMA position to find the winning conditions.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
import pandas as pd
import ta
from datetime import datetime
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

# ─── Config ──────────────────────────────────────────────────────────────────
SL_PTS   = 10.0   # Stop loss in points
TP1_PTS  =  5.0   # TP target 1
TP2_PTS  = 10.0   # TP target 2
TP3_PTS  = 15.0   # TP target 3
GAP_TOL  =  0.09  # Micro-gap tolerance (matches live engine)
MIN_SAMPLES = 30  # Minimum occurrences to be statistically reliable

# ─── MT5 data fetch ──────────────────────────────────────────────────────────
def fetch_data():
    if not mt5.initialize():
        raise RuntimeError("MT5 init failed")

    m5_rates  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5,  0, 50000)
    h1_rates  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1,  0, 10000)
    h4_rates  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H4,  0,  3000)

    m5 = pd.DataFrame(m5_rates)
    h1 = pd.DataFrame(h1_rates)
    h4 = pd.DataFrame(h4_rates)

    for df in (m5, h1, h4):
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)

    return m5, h1, h4

# ─── Indicators ──────────────────────────────────────────────────────────────
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_20"]  = ta.trend.ema_indicator(df["close"], window=20)
    df["ema_50"]  = ta.trend.ema_indicator(df["close"], window=50)
    df["ema_200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["atr"]     = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
    return df

# ─── H4 / H1 trend at a given UTC timestamp ──────────────────────────────────
def get_h4_trend(h4: pd.DataFrame, ts) -> str:
    past = h4[h4.index <= ts]
    if len(past) < 50:
        return "MIXED"
    row = past.iloc[-1]
    if row["ema_20"] > row["ema_50"]:
        return "BULLISH"
    elif row["ema_20"] < row["ema_50"]:
        return "BEARISH"
    return "MIXED"

def get_h1_trend(h1: pd.DataFrame, ts) -> str:
    past = h1[h1.index <= ts]
    if len(past) < 50:
        return "MIXED"
    row = past.iloc[-1]
    if row["ema_20"] > row["ema_50"]:
        return "BULLISH"
    elif row["ema_20"] < row["ema_50"]:
        return "BEARISH"
    return "MIXED"

# ─── Session ─────────────────────────────────────────────────────────────────
def get_session(ts) -> str:
    hour = ts.astimezone(EST).hour
    in_london = 3  <= hour < 8
    in_ny     = 8  <= hour < 13
    if in_london and in_ny:
        return "OVERLAP"
    if in_london:
        return "LONDON"
    if in_ny:
        return "NY"
    if hour >= 19 or hour < 3:
        return "ASIAN"
    return "OFF"

# ─── ATR regime ──────────────────────────────────────────────────────────────
def get_atr_regime(atr: float) -> str:
    if atr < 3.0:
        return "LOW"
    if atr < 7.0:
        return "NORMAL"
    if atr < 12.0:
        return "HIGH"
    return "EXTREME"

# ─── Body size ───────────────────────────────────────────────────────────────
def get_body_size(o, c) -> str:
    body = abs(c - o)
    if body < 1.0:
        return "SMALL"
    if body < 3.0:
        return "MEDIUM"
    return "LARGE"

# ─── EMA position ────────────────────────────────────────────────────────────
def get_ema_pos(price, ema20, ema50) -> str:
    above20 = price > ema20 if not pd.isna(ema20) else False
    above50 = price > ema50 if not pd.isna(ema50) else False
    if above20 and above50:
        return "ABOVE_BOTH"
    if not above20 and not above50:
        return "BELOW_BOTH"
    return "BETWEEN"

# ─── Simulate trade outcome ───────────────────────────────────────────────────
def simulate_outcome(m5: pd.DataFrame, entry_idx: int, direction: str) -> dict:
    """Look forward up to 48 candles (4 hours) to see if TP or SL is hit."""
    entry_price = float(m5["open"].iloc[entry_idx])

    if direction == "BULLISH":
        sl_price  = entry_price - SL_PTS
        tp1_price = entry_price + TP1_PTS
        tp2_price = entry_price + TP2_PTS
        tp3_price = entry_price + TP3_PTS
    else:
        sl_price  = entry_price + SL_PTS
        tp1_price = entry_price - TP1_PTS
        tp2_price = entry_price - TP2_PTS
        tp3_price = entry_price - TP3_PTS

    hit_tp1 = hit_tp2 = hit_tp3 = False
    exit_pts = None
    exit_reason = "TIMEOUT"
    candles_held = 0

    for i in range(entry_idx + 1, min(entry_idx + 49, len(m5))):
        row = m5.iloc[i]
        h, l = float(row["high"]), float(row["low"])
        candles_held += 1

        if direction == "BULLISH":
            if l <= sl_price:
                exit_pts = -SL_PTS
                exit_reason = "SL"
                break
            hit_tp3 = hit_tp3 or h >= tp3_price
            hit_tp2 = hit_tp2 or h >= tp2_price
            hit_tp1 = hit_tp1 or h >= tp1_price
            if h >= tp3_price:
                exit_pts = TP3_PTS
                exit_reason = "TP3"
                break
        else:
            if h >= sl_price:
                exit_pts = -SL_PTS
                exit_reason = "SL"
                break
            hit_tp3 = hit_tp3 or l <= tp3_price
            hit_tp2 = hit_tp2 or l <= tp2_price
            hit_tp1 = hit_tp1 or l <= tp1_price
            if l <= tp3_price:
                exit_pts = TP3_PTS
                exit_reason = "TP3"
                break

    if exit_pts is None:
        exit_pts = float(m5["close"].iloc[min(entry_idx + 48, len(m5) - 1)]) - entry_price
        if direction == "BULLISH":
            exit_pts = float(m5["close"].iloc[min(entry_idx + 48, len(m5) - 1)]) - entry_price
        else:
            exit_pts = entry_price - float(m5["close"].iloc[min(entry_idx + 48, len(m5) - 1)])

    return {
        "exit_pts":     round(exit_pts, 2),
        "exit_reason":  exit_reason,
        "hit_tp1":      hit_tp1,
        "hit_tp2":      hit_tp2,
        "hit_tp3":      hit_tp3,
        "win_5":        hit_tp1,
        "win_10":       hit_tp2,
        "win_15":       hit_tp3,
        "candles_held": candles_held,
    }

# ─── Main scan ───────────────────────────────────────────────────────────────
def run_backtest():
    print("Fetching data from MT5...")
    m5, h1, h4 = fetch_data()
    print(f"  M5 bars: {len(m5)} | H1 bars: {len(h1)} | H4 bars: {len(h4)}")
    print("Computing indicators...")
    m5 = add_indicators(m5)
    h1 = add_indicators(h1)
    h4 = add_indicators(h4)
    print("Scanning for signals...")

    records = []
    START = 200  # skip warmup

    for i in range(START, len(m5) - 50):
        curr = m5.iloc[i]
        prev = m5.iloc[i - 1]
        ts   = m5.index[i]

        curr_open  = float(curr["open"])
        curr_close = float(curr["close"])
        prev_open  = float(prev["open"])
        prev_close = float(prev["close"])

        prev_bearish = prev_close < prev_open
        prev_bullish = prev_close > prev_open

        # Crown Momentum (BUY): prev bullish, current opens at/above prev close
        crown = prev_bullish and (curr_open >= prev_close - GAP_TOL)

        # Base Momentum (SELL): prev bearish, current opens at/below prev close
        base  = prev_bearish and (curr_open <= prev_close + GAP_TOL)

        if not crown and not base:
            continue

        direction = "BULLISH" if crown else "BEARISH"
        setup     = "CROWN" if crown else "BASE"

        # Context
        h4_trend  = get_h4_trend(h4, ts)
        h1_trend  = get_h1_trend(h1, ts)
        session   = get_session(ts)
        atr_val   = float(curr["atr"]) if not pd.isna(curr["atr"]) else 5.0
        atr_reg   = get_atr_regime(atr_val)
        body_size = get_body_size(prev_open, prev_close)
        ema_pos   = get_ema_pos(curr_open,
                                 float(curr["ema_20"]) if not pd.isna(curr["ema_20"]) else curr_open,
                                 float(curr["ema_50"]) if not pd.isna(curr["ema_50"]) else curr_open)

        # Simulate
        outcome = simulate_outcome(m5, i, direction)

        records.append({
            "time":      ts,
            "setup":     setup,
            "direction": direction,
            "session":   session,
            "h4_trend":  h4_trend,
            "h1_trend":  h1_trend,
            "atr_regime": atr_reg,
            "body_size": body_size,
            "ema_pos":   ema_pos,
            **outcome,
        })

    df = pd.DataFrame(records)
    print(f"\nTotal signals found: {len(df)} (Crown: {(df.setup=='CROWN').sum()} | Base: {(df.setup=='BASE').sum()})\n")
    return df

# ─── Analysis ────────────────────────────────────────────────────────────────
def analyse(df: pd.DataFrame):
    print("=" * 80)
    print("  BACKTEST RESULTS: CROWN MOMENTUM (BUY) vs BASE MOMENTUM (SELL)")
    print("=" * 80)

    for setup in ["CROWN", "BASE"]:
        sub = df[df["setup"] == setup]
        n   = len(sub)
        if n == 0:
            continue

        direction_label = "BUY" if setup == "CROWN" else "SELL"
        print(f"\n{'─'*80}")
        print(f"  {setup} MOMENTUM ({direction_label})  |  n={n}")
        print(f"{'─'*80}")

        for label, col in [("Reach +5  pts", "win_5"), ("Reach +10 pts", "win_10"), ("Reach +15 pts", "win_15")]:
            rate = sub[col].mean() * 100
            print(f"  {label}: {rate:.1f}%")

        print(f"\n  Average exit: {sub['exit_pts'].mean():.2f} pts | Median: {sub['exit_pts'].median():.2f} pts")
        print(f"  Best: {sub['exit_pts'].max():.1f} pts  |  Worst: {sub['exit_pts'].min():.1f} pts")
        print(f"  Avg candles held: {sub['candles_held'].mean():.1f}")

        # ── Segment analysis ──
        segments = [
            ("H4 Trend",   "h4_trend"),
            ("H1 Trend",   "h1_trend"),
            ("Session",    "session"),
            ("ATR Regime", "atr_regime"),
            ("Prev Body",  "body_size"),
            ("EMA Pos",    "ema_pos"),
        ]

        for seg_label, col in segments:
            print(f"\n  [{seg_label}]")
            for val in sub[col].unique():
                grp = sub[sub[col] == val]
                if len(grp) < MIN_SAMPLES:
                    print(f"    {val:<20} n={len(grp):>5}  (skip — too few samples)")
                    continue
                w5  = grp["win_5"].mean()  * 100
                w10 = grp["win_10"].mean() * 100
                w15 = grp["win_15"].mean() * 100
                avg = grp["exit_pts"].mean()
                flag = "  <<< SWEET SPOT" if w10 >= 60 else ""
                print(f"    {val:<20} n={len(grp):>5}  +5pt={w5:5.1f}%  +10pt={w10:5.1f}%  +15pt={w15:5.1f}%  avg={avg:+.2f}{flag}")

    # ── Combined best conditions ──
    print(f"\n{'='*80}")
    print("  BEST CONDITIONS (Win rate >= 60% at +10pt, n >= 30)")
    print(f"{'='*80}")
    found = False
    for setup in ["CROWN", "BASE"]:
        sub = df[df["setup"] == setup]
        for seg_col in ["h4_trend", "h1_trend", "session", "atr_regime", "body_size", "ema_pos"]:
            for val in sub[seg_col].unique():
                grp = sub[sub[seg_col] == val]
                if len(grp) >= MIN_SAMPLES and grp["win_10"].mean() >= 0.60:
                    rate = grp["win_10"].mean() * 100
                    found = True
                    print(f"  {setup} | {seg_col}={val:<15} | n={len(grp):>5} | win@10pt={rate:.1f}%")
    if not found:
        print("  No single condition exceeds 60% win rate at +10pt target.")

    print(f"\n{'='*80}\n")

    return df

# ─── Entry ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    df = run_backtest()
    analyse(df)
    # Save raw results for further analysis
    out_path = os.path.join(os.path.dirname(__file__), "backtest_momentum_results.csv")
    df.to_csv(out_path, index=False)
    print(f"Raw results saved to: {out_path}")
