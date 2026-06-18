"""
bounce_analysis.py — H1 Swing Low Bounce Counter

For the last 30 days of XAUUSD H1 data, counts every instance where:
  1. A swing low formed within the last 6 H1 bars
  2. Price bounced at least 15 pips (1.5 Gold points) from that swing low
  3. Price then continued downward and broke below that swing low within the next 5 H1 bars

This is EMA-agnostic — it measures raw price action only.

Usage (from backend/ directory):
    uv run python bounce_analysis.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.CRITICAL)

import pandas as pd
from datetime import datetime, timedelta, timezone

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

BOUNCE_THRESHOLD_POINTS = 1.5   # 15 pips for XAU/USD (1 pip = 0.1 points)
SWING_WINDOW            = 6     # candles to look back for swing low
CONTINUATION_WINDOW     = 5     # bars forward to check for new low (downward continuation)
TEST_DAYS               = 30
FETCH_DAYS              = 37    # extra 7 days so EMAs and window are warm

# ─────────────────────────────────────────────────────────────────────────────
# MT5 connection
# ─────────────────────────────────────────────────────────────────────────────

try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERROR: MetaTrader5 not installed.  Run: uv add MetaTrader5")
    sys.exit(1)

from app.settings import settings

print("Connecting to MetaTrader 5 ...")
ok = mt5.initialize(login=settings.mt5_login, password=settings.mt5_password,
                    server=settings.mt5_server)
if not ok:
    print(f"MT5 init failed: {mt5.last_error()}")
    sys.exit(1)

info = mt5.account_info()
print(f"  Connected: {info.server}  |  Account: {info.login}\n")

SYMBOL = (settings.force_symbol or "").strip() or "XAUUSD"
end_dt   = datetime.now(timezone.utc)
start_dt = end_dt - timedelta(days=FETCH_DAYS)

rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_H1, start_dt, end_dt)
mt5.shutdown()

if rates is None or len(rates) == 0:
    print("ERROR: No H1 data returned from MT5.")
    sys.exit(1)

df = pd.DataFrame(rates)
df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
df.set_index("time", inplace=True)
df.rename(columns={"tick_volume": "volume"}, inplace=True)
df = df[["open", "high", "low", "close", "volume"]]

cutoff = end_dt - timedelta(days=TEST_DAYS)
df_test = df[df.index >= cutoff].reset_index()   # flat index so we can do forward-look by position

print(f"H1 candles fetched: {len(df)}  |  Test window: {len(df_test)} candles "
      f"from {cutoff.strftime('%Y-%m-%d %H:%M')} UTC")
print(f"Bounce threshold  : {BOUNCE_THRESHOLD_POINTS} points ({int(BOUNCE_THRESHOLD_POINTS*10)} pips)")
print(f"Swing window      : last {SWING_WINDOW} H1 bars")
print(f"Continuation check: next {CONTINUATION_WINDOW} H1 bars\n")

# ─────────────────────────────────────────────────────────────────────────────
# Walk every H1 candle in the test window
# ─────────────────────────────────────────────────────────────────────────────

bounce_events      = []   # all bounces >= threshold
continuation_events = []  # bounces that then broke the swing low

# We need SWING_WINDOW bars of history before the test window starts,
# so we walk starting at index SWING_WINDOW within df_test.
n = len(df_test)

for i in range(SWING_WINDOW, n):
    row      = df_test.iloc[i]
    ts       = row["time"]
    cur_close = float(row["close"])
    cur_high  = float(row["high"])

    # --- Swing low in the last SWING_WINDOW bars (not including current) ---
    window = df_test.iloc[i - SWING_WINDOW: i]
    swing_low_val = float(window["low"].min())
    swing_low_ts  = window.loc[window["low"].idxmin(), "time"]

    # Bounce height = current bar's high minus the swing low
    bounce_pts = cur_high - swing_low_val

    if bounce_pts < BOUNCE_THRESHOLD_POINTS:
        continue   # bounce too small, skip

    # Bounce found — record it
    event = {
        "timestamp (UTC)":  ts.strftime("%Y-%m-%d %H:%M"),
        "swing_low_ts":     swing_low_ts.strftime("%Y-%m-%d %H:%M"),
        "swing_low":        round(swing_low_val, 2),
        "cur_close":        round(cur_close, 2),
        "bounce_pts":       round(bounce_pts, 2),
        "bounce_pips":      round(bounce_pts * 10, 1),
        "continued_down":   False,
        "bars_to_break":    None,
    }

    # --- Check if price broke below swing low in the next N bars ---
    future = df_test.iloc[i + 1: i + 1 + CONTINUATION_WINDOW]
    for offset, (_, frow) in enumerate(future.iterrows(), start=1):
        if float(frow["low"]) < swing_low_val:
            event["continued_down"] = True
            event["bars_to_break"]  = offset
            break

    bounce_events.append(event)
    if event["continued_down"]:
        continuation_events.append(event)

# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────

SEP = "=" * 72

print(SEP)
print(f"  ALL H1 BOUNCES >= {BOUNCE_THRESHOLD_POINTS} pts from recent swing low  "
      f"({len(bounce_events)} events)")
print(SEP)

if bounce_events:
    df_ev = pd.DataFrame(bounce_events)
    with pd.option_context("display.max_rows", None, "display.width", 120,
                           "display.float_format", "{:.2f}".format):
        print(df_ev.to_string(index=False))
    print()

    # Bounce size distribution
    sizes = df_ev["bounce_pts"]
    print(f"  Bounce size stats (points):  "
          f"min={sizes.min():.2f}  median={sizes.median():.2f}  "
          f"mean={sizes.mean():.2f}  max={sizes.max():.2f}")
    buckets = pd.cut(sizes, bins=[1.5, 2, 3, 5, 10, 9999],
                     labels=["1.5-2", "2-3", "3-5", "5-10", ">10"])
    print("  Bounce size buckets:")
    for bucket, count in buckets.value_counts().sort_index().items():
        print(f"    {str(bucket):<8}: {count}")
else:
    print("  No bounces found.")

print()
print(SEP)
print(f"  BOUNCES THAT CONTINUED DOWNWARD (broke swing low within {CONTINUATION_WINDOW} bars)  "
      f"({len(continuation_events)}  /  {len(bounce_events)}  = "
      f"{len(continuation_events)/len(bounce_events)*100:.1f}% of all bounces)" if bounce_events else "")
print(SEP)

if continuation_events:
    df_cont = pd.DataFrame(continuation_events)
    # Speed of continuation
    speeds = df_cont["bars_to_break"].value_counts().sort_index()
    print("  Bars until new low:")
    for bars, count in speeds.items():
        print(f"    {bars} bar(s): {count}")
    print()
    # Biggest bounces that still continued
    print("  Top 10 largest bounces that still continued downward:")
    top = df_cont.sort_values("bounce_pts", ascending=False).head(10)
    with pd.option_context("display.max_rows", None, "display.width", 120):
        print(top[["timestamp (UTC)", "swing_low", "cur_close", "bounce_pts",
                   "bounce_pips", "bars_to_break"]].to_string(index=False))
else:
    print("  None of the bounces led to a continuation within the window.")

print()
print(SEP)
print(f"  SUMMARY")
print(SEP)
print(f"  Test period         : last {TEST_DAYS} days ({len(df_test)} H1 candles)")
print(f"  Total bounces found : {len(bounce_events)}")
print(f"  Continued downward  : {len(continuation_events)}  "
      f"({len(continuation_events)/len(bounce_events)*100:.1f}%)" if bounce_events else "  No bounces found")
print(f"  Faded / reversed    : {len(bounce_events) - len(continuation_events)}  "
      f"({(len(bounce_events)-len(continuation_events))/len(bounce_events)*100:.1f}%)" if bounce_events else "")
print()
print("  A high 'continued downward' % confirms pullback-then-resume is a real")
print("  pattern in this data. A low % means most bounces turned into reversals.")
