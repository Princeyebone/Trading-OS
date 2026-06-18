"""
backtest_scalping_engine.py — Backtest the new M5 Scalping System.
"""

import sys
import os
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Suppress engine chatter
logging.basicConfig(level=logging.CRITICAL)
for noisy in ("engine.scalping", "app.settings"):
    logging.getLogger(noisy).setLevel(logging.CRITICAL)

try:
    import MetaTrader5 as mt5
except ImportError:
    print("ERROR: MetaTrader5 package not installed. Make sure you are using the .venv python environment.")
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
    sys.exit(1)

info = mt5.account_info()
print(f"  Connected to: {info.server}  |  Account: {info.login}  |  Balance: {info.balance}\n")

SYMBOL = (settings.force_symbol or "").strip() or "XAUUSD"

# 14 days for M5 is plenty
end_dt = datetime.now(timezone.utc)
start_dt = end_dt - timedelta(days=14)

print(f"Fetching M5 data for {SYMBOL} from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}...")
m5_rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, start_dt, end_dt)
m15_rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M15, start_dt, end_dt)
mt5.shutdown()

if m5_rates is None or len(m5_rates) < 100:
    print("Failed to fetch enough M5 data.")
    sys.exit(1)

raw_m5 = pd.DataFrame(m5_rates)
raw_m5['time'] = pd.to_datetime(raw_m5['time'], unit='s', utc=True)
raw_m5.set_index('time', inplace=True)

raw_m15 = pd.DataFrame(m15_rates)
raw_m15['time'] = pd.to_datetime(raw_m15['time'], unit='s', utc=True)
raw_m15.set_index('time', inplace=True)

from engine.scalping_engine import ScalpingEngine

print("\nRunning Phase 1: Breakout Scalp Backtest...")
engine = ScalpingEngine(raw_m5, raw_m15)
all_signals = engine.backtest(start_idx=100)

print("\n" + "="*72)
print("  SCALPING BACKTEST RESULTS")
print("="*72)
breakout_signals = [s for s in all_signals if s['type'] == 'BREAKOUT']
fibonacci_signals = [s for s in all_signals if s['type'] == 'FIBONACCI']
ema_signals = [s for s in all_signals if s['type'] == 'EMA_PULLBACK']
range_signals = [s for s in all_signals if s['type'] == 'RANGE_BOUNCE']
range_breakout_signals = [s for s in all_signals if s['type'] == 'RANGE_BREAKOUT']

# Apply dynamic spread filter (0.5 spread)
SPREAD = 0.5
valid_signals = []
for s in all_signals:
    if s['direction'] == 'BULLISH':
        effective_tp = s['tp1'] - SPREAD
        effective_sl = s['sl'] + SPREAD
    else:
        effective_tp = s['tp1'] + SPREAD
        effective_sl = s['sl'] - SPREAD
        
    risk = abs(s['entry'] - effective_sl)
    reward = abs(effective_tp - s['entry'])
    effective_rr = reward / risk if risk > 0 else 0
    
    if effective_rr >= 1.2:
        s['rr'] = round(effective_rr, 2)
        valid_signals.append(s)

print(f"Total scalping signals BEFORE filter: {len(all_signals)}")
print(f"Total scalping signals AFTER filter: {len(valid_signals)}")
print(f"Breakout signals: {len(breakout_signals)}")
print(f"Fibonacci signals: {len(fibonacci_signals)}")
print(f"EMA Pullback signals: {len(ema_signals)}")
print(f"Range Bounce signals: {len(range_signals)}")
print(f"Range Breakout signals: {len(range_breakout_signals)}")

if breakout_signals:
    df_signals = pd.DataFrame(breakout_signals)
    df_signals['timestamp'] = df_signals['timestamp'].dt.strftime("%Y-%m-%d %H:%M")
    
    print("\n--- SAMPLE BREAKOUT SIGNALS ---")
    with pd.option_context("display.max_rows", None, "display.width", 120):
        print(df_signals[['timestamp', 'direction', 'price', 'entry', 'sl', 'tp1', 'rr']].tail(10).to_string(index=False))

if fibonacci_signals:
    df_fib = pd.DataFrame(fibonacci_signals)
    df_fib['timestamp'] = df_fib['timestamp'].dt.strftime("%Y-%m-%d %H:%M")
    
    print("\n--- SAMPLE FIBONACCI SIGNALS ---")
    with pd.option_context("display.max_rows", None, "display.width", 120):
        print(df_fib[['timestamp', 'direction', 'price', 'entry', 'sl', 'tp1', 'rr']].tail(10).to_string(index=False))

if ema_signals:
    df_ema = pd.DataFrame(ema_signals)
    df_ema['timestamp'] = df_ema['timestamp'].dt.strftime("%Y-%m-%d %H:%M")
    
    print("\n--- SAMPLE EMA PULLBACK SIGNALS ---")
    with pd.option_context("display.max_rows", None, "display.width", 120):
        print(df_ema[['timestamp', 'direction', 'price', 'entry', 'sl', 'tp1', 'rr']].tail(10).to_string(index=False))

if range_signals:
    df_range = pd.DataFrame(range_signals)
    df_range['timestamp'] = df_range['timestamp'].dt.strftime("%Y-%m-%d %H:%M")
    
    print("\n--- SAMPLE RANGE BOUNCE SIGNALS ---")
    with pd.option_context("display.max_rows", None, "display.width", 120):
        print(df_range[['timestamp', 'direction', 'price', 'entry', 'sl', 'tp1', 'rr']].tail(10).to_string(index=False))

if range_breakout_signals:
    df_rb = pd.DataFrame(range_breakout_signals)
    df_rb['timestamp'] = df_rb['timestamp'].dt.strftime("%Y-%m-%d %H:%M")
    
    print("\n--- SAMPLE RANGE BREAKOUT SIGNALS ---")
    with pd.option_context("display.max_rows", None, "display.width", 120):
        print(df_rb[['timestamp', 'direction', 'price', 'entry', 'sl', 'tp1', 'rr']].tail(10).to_string(index=False))

print("\nFinished backtest.")
