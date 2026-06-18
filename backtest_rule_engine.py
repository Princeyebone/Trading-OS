"""
backtest_rule_engine.py — 48-hour walk-forward backtest using LIVE MT5 data.

Connects to your MT5 terminal, pulls the last 72 hours of XAUUSD data
(extra 24h for EMA warm-up), then walks every M15 candle in the 48-hour
window and checks whether TCP rules would have fired.

Usage (from backend/ directory):
    uv run python backtest_rule_engine.py

Output:
    - Every timestamp where ALL 5 rules passed (with Entry, SL, TP1, TP2, RR)
    - Rule failure frequency table — shows which condition blocks most often
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()
    def flush(self):
        for f in self.files:
            f.flush()

f = open("backtest_results.txt", "w", encoding="utf-8")
sys.stdout = Tee(sys.stdout, f)

# ── silence everything except our own output ──────────────────────────────────
import logging
logging.basicConfig(level=logging.CRITICAL)   # suppress engine chatter
for noisy in ("engine.rule_engine", "engine.broker_executor", "app.settings"):
    logging.getLogger(noisy).setLevel(logging.CRITICAL)

import pandas as pd
from datetime import datetime, timedelta, timezone

# ─────────────────────────────────────────────────────────────────────────────
# MT5 connection
# ─────────────────────────────────────────────────────────────────────────────

try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERROR: MetaTrader5 package not installed.")
    print("       Run: uv add MetaTrader5")
    sys.exit(1)

from app.settings import settings

print("Connecting to MetaTrader 5...")
ok = mt5.initialize(
    login=settings.mt5_login,
    password=settings.mt5_password,
    server=settings.mt5_server,
)
if not ok:
    print(f"ERROR: MT5 failed to initialize — {mt5.last_error()}")
    print("  Make sure the MT5 terminal is open and you are logged in.")
    sys.exit(1)

info = mt5.account_info()
print(f"  Connected to: {info.server}  |  Account: {info.login}  |  Balance: {info.balance}\n")

# Detect symbol — respect FORCE_SYMBOL override
SYMBOL = (settings.force_symbol or "").strip() or "XAUUSD"

# ─────────────────────────────────────────────────────────────────────────────
# Fetch raw candles from MT5 using copy_rates_range
# ─────────────────────────────────────────────────────────────────────────────

end_dt   = datetime.now(timezone.utc)
start_dt = end_dt - timedelta(days=70)    # 70-day fetch → 40-day EMA-200 warm-up + 30-day test
# NOTE: H4 EMA-200 needs 200 bars × 4h = 33+ days of warm-up before the test window.
#       37 days was too short (≈160 H4 bars only). 70 days gives ≈300 H4 bars.

TF_MAP = {
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
}

def fetch_mt5(timeframe_str: str) -> pd.DataFrame:
    """Pull OHLCV from MT5 for the given timeframe string over the 72h window."""
    rates = mt5.copy_rates_range(
        SYMBOL,
        TF_MAP[timeframe_str],
        start_dt,   # MT5 accepts aware datetimes
        end_dt,
    )
    if rates is None or len(rates) == 0:
        print(f"ERROR: MT5 returned no data for {SYMBOL} {timeframe_str}")
        print(f"       Error: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


print(f"Fetching {SYMBOL} data from MT5 (70-day window, 30-day test) ...")
raw_m15 = fetch_mt5("M15")
raw_h1  = fetch_mt5("H1")
raw_h4  = fetch_mt5("H4")

mt5.shutdown()   # release the connection immediately — we have everything we need
print(f"  M15: {len(raw_m15)} candles  |  H1: {len(raw_h1)} candles  |  H4: {len(raw_h4)} candles")

# ─────────────────────────────────────────────────────────────────────────────
# Compute indicators on full series (same as live pipeline)
# ─────────────────────────────────────────────────────────────────────────────

from engine import indicators as ind_module

print("Computing indicators ...")
tf_full  = ind_module.compute_all_indicators({"M15": raw_m15, "H1": raw_h1, "H4": raw_h4})
m15_full = tf_full["M15"]
h1_full  = tf_full["H1"]
h4_full  = tf_full["H4"]

# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward: evaluate TCP rules at every M15 candle in the last 48 hours
# ─────────────────────────────────────────────────────────────────────────────

from engine.rule_engine import evaluate_tcp_bearish, evaluate_tcp_bullish, score_h4_trend

cutoff      = end_dt - timedelta(days=30)
test_idxs   = [i for i, ts in enumerate(m15_full.index) if ts >= cutoff]

# Failure counters for the scoring system
low_score_count = 0
poor_rr_count = 0
score_distribution = []

bearish_fires = []
bullish_fires = []

print(f"\nWalking {len(test_idxs)} M15 candles from "
      f"{cutoff.strftime('%Y-%m-%d %H:%M')} UTC  (30-day window) ...\n")

for idx in test_idxs:
    ts = m15_full.index[idx]

    m15_slice = m15_full.iloc[: idx + 1]
    h1_slice  = h1_full[h1_full.index <= ts]
    h4_slice  = h4_full[h4_full.index <= ts]

    if len(h1_slice) < 15 or len(h4_slice) < 15 or len(m15_slice) < 15:
        continue

    tf_snap = {"M15": m15_slice, "H1": h1_slice, "H4": h4_slice}

    # ── Bearish ──
    b_res = evaluate_tcp_bearish(tf_snap)
    if b_res["verdict"] == "TRADE":
        bearish_fires.append({
            "timestamp (UTC)": ts.strftime("%Y-%m-%d %H:%M"),
            "score":  b_res["confidence"],
            "entry":  b_res["entry"],
            "sl":     b_res["sl"],
            "tp1":    b_res["tp1"],
            "tp2":    b_res["tp2"],
            "rr":     b_res["rr"],
            "breakdown": b_res["reason"]
        })
    else:
        reason = b_res.get("reason", "UNKNOWN")
        rules = b_res.get("rules_checked", {})
        if "LOW_SCORE" in reason:
            low_score_count += 1
            if "score" in rules:
                score_distribution.append(rules["score"])
        elif "POOR_RR" in reason:
            poor_rr_count += 1

    # ── Bullish ──
    u_res = evaluate_tcp_bullish(tf_snap)
    if u_res["verdict"] == "TRADE":
        bullish_fires.append({
            "timestamp (UTC)": ts.strftime("%Y-%m-%d %H:%M"),
            "score":  u_res["confidence"],
            "entry":  u_res["entry"],
            "sl":     u_res["sl"],
            "tp1":    u_res["tp1"],
            "tp2":    u_res["tp2"],
            "rr":     u_res["rr"],
            "breakdown": u_res["reason"]
        })

# ─────────────────────────────────────────────────────────────────────────────
# Print results
# ─────────────────────────────────────────────────────────────────────────────

SEP = "=" * 72

print(SEP)
print("  TCP BEARISH (SHORT) — SCORE >= 70  [last 30 days]")
print(SEP)
if bearish_fires:
    df_b = pd.DataFrame(bearish_fires)
    print(df_b.to_string(index=False))
else:
    print("  No bearish setups fired in the last 30 days.")

print()
print(SEP)
print("  TCP BULLISH (LONG) — SCORE >= 70  [last 30 days]")
print(SEP)
if bullish_fires:
    df_u = pd.DataFrame(bullish_fires)
    print(df_u.to_string(index=False))
else:
    print("  No bullish setups fired in the last 30 days.")

print()
print()
print(SEP)
print("  SCORING DIAGNOSTICS")
print(SEP)
print(f"  Total candles tested : {len(test_idxs)}")
print(f"  Low Score (< 70)     : {low_score_count}")
print(f"  Poor RR (score >= 70): {poor_rr_count}")
print(f"  Bearish Fired        : {len(bearish_fires)}")
print(f"  Bullish Fired        : {len(bullish_fires)}")

if score_distribution:
    df_scores = pd.Series(score_distribution)
    print("\n  Score Distribution (all failed candles):")
    print(f"    Mean Score  : {df_scores.mean():.1f}")
    print(f"    Max Score   : {df_scores.max():.1f}")
    
    # Bucket scores
    buckets = pd.cut(df_scores, bins=[-1, 20, 40, 50, 60, 69])
    print(f"\n  Buckets (Failed setups):")
    for bucket, count in buckets.value_counts().sort_index().items():
        print(f"    {str(bucket):<15}: {count}")

print("\n" + "="*72)
print("  BULLISH TREND DIAGNOSTICS")
print("="*72)

# Check how many candles passed the H4 WEAK or STRONG bullish logic
bullish_h4_pass = 0
for idx in test_idxs:
    ts = m15_full.index[idx]
    h4_slice  = h4_full[h4_full.index <= ts]
    if len(h4_slice) >= 15:
        score, label = score_h4_trend(h4_slice, "BULLISH")
        if "STRONG_BULLISH" in label or "WEAK_BULLISH" in label:
            bullish_h4_pass += 1
            
print(f"  Total candles passing Bullish H4 criteria: {bullish_h4_pass} / {len(test_idxs)}")

print("\n" + "="*72)
print("  SIGNAL QUALITY ANALYSIS")
print("="*72)

if len(bearish_fires) > 0:
    df_b = pd.DataFrame(bearish_fires)
    print(f"Bearish signals: {len(bearish_fires)}")
    print(f"  Avg Score: {df_b['score'].mean():.0f}")
    print(f"  Avg RR: {df_b['rr'].mean():.2f}")
    print(f"  Score range: {df_b['score'].min()} - {df_b['score'].max()}")
else:
    print("No bearish signals")

if len(bullish_fires) > 0:
    df_u = pd.DataFrame(bullish_fires)
    print(f"Bullish signals: {len(bullish_fires)}")
    print(f"  Avg Score: {df_u['score'].mean():.0f}")
    print(f"  Avg RR: {df_u['rr'].mean():.2f}")
    print(f"  Score range: {df_u['score'].min()} - {df_u['score'].max()}")
else:
    print("No bullish signals - run to check if H4 trend detection fixed it!")
