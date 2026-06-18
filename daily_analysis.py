"""
Daily Trade Analysis Script
Pulls all today's trades, compares signals to actual market moves,
and produces a comprehensive performance report.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.db import get_session
from app.models.trades import Trade, TradeOutcome, TradeJournal
from app.models.signals import Signal
from sqlmodel import select
import MetaTrader5 as mt5

session = get_session()
today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

if not mt5.initialize():
    print("MT5 init failed")
    sys.exit(1)

trades = session.exec(
    select(Trade).where(Trade.opened_at >= today_start).order_by(Trade.opened_at)
).all()

print(f"{'='*80}")
print(f"  DAILY PERFORMANCE ANALYSIS — {datetime.now().strftime('%Y-%m-%d')}")
print(f"{'='*80}")
print(f"\nTotal trades found: {len(trades)}\n")

results = []
scalp_wins = scalp_losses = scalp_pnl = scalp_pips = 0
tcp_wins = tcp_losses = tcp_pnl = tcp_pips = 0
open_count = 0

print(f"{'─'*80}")
print(f"{'#':<5} {'Session':<10} {'Dir':<6} {'Entry':<9} {'Exit':<9} {'Signal':<20} {'Status':<8} {'Pips':>7} {'P&L ($)':>9} {'Accuracy'}")
print(f"{'─'*80}")

for t in trades:
    outcome = session.exec(select(TradeOutcome).where(TradeOutcome.trade_id == t.id)).first()
    signal  = session.exec(select(Signal).where(Signal.id == t.signal_id)).first() if t.signal_id else None

    if not outcome or t.status == "OPEN":
        open_count += 1
        session_name = signal.session if signal else "UNKNOWN"
        print(f"#{t.id:<4} {session_name:<10} {t.direction:<6} {(t.actual_entry or 0):<9.2f} {'OPEN':<9} {'-':<20} {'OPEN':<8} {'---':>7} {'---':>9} PENDING")
        continue

    session_name = signal.session if signal else "UNKNOWN"
    entry   = t.actual_entry or 0
    exit_px = outcome.exit_price or 0
    pips    = outcome.pnl_pips or 0
    dollars = outcome.pnl_dollars or 0
    status  = t.status or "?"

    # Signal accuracy: did the price move in our predicted direction?
    if entry and exit_px:
        predicted_long  = t.direction == "LONG"
        actual_moved_up = exit_px > entry
        correct = (predicted_long and actual_moved_up) or (not predicted_long and not actual_moved_up)
    else:
        correct = False

    accuracy = "✓ CORRECT" if correct else "✗ WRONG"
    sig_type = getattr(signal, 'timeframe', '-') if signal else '-'

    # Categorise
    is_scalp = session_name == "SCALP"
    if is_scalp:
        if status == "WIN":   scalp_wins  += 1
        elif status == "LOSS": scalp_losses += 1
        scalp_pnl  += dollars
        scalp_pips += pips
    else:
        if status == "WIN":   tcp_wins  += 1
        elif status == "LOSS": tcp_losses += 1
        tcp_pnl  += dollars
        tcp_pips += pips

    results.append(correct)

    print(f"#{t.id:<4} {session_name:<10} {t.direction:<6} {entry:<9.2f} {exit_px:<9.2f} {sig_type:<20} {status:<8} {pips:>7.1f} {dollars:>9.2f} {accuracy}")

print(f"{'─'*80}\n")

# ── SUMMARY ──────────────────────────────────────────────────────────────────
total_trades  = scalp_wins + scalp_losses + tcp_wins + tcp_losses
total_wins    = scalp_wins + tcp_wins
total_losses  = scalp_losses + tcp_losses
total_pnl     = round(scalp_pnl + tcp_pnl, 2)
total_pips    = round(scalp_pips + tcp_pips, 1)
accuracy_pct  = round(sum(results) / len(results) * 100, 1) if results else 0.0
win_rate      = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0.0

print(f"{'='*80}")
print(f"  SUMMARY")
print(f"{'='*80}")
print(f"\n  {'OVERALL':}")
print(f"  ├─ Closed Trades   : {total_trades}  (+ {open_count} still open)")
print(f"  ├─ Wins            : {total_wins}")
print(f"  ├─ Losses          : {total_losses}")
print(f"  ├─ Win Rate        : {win_rate}%")
print(f"  ├─ Signal Accuracy : {accuracy_pct}%  ({sum(results)}/{len(results)} predictions correct)")
print(f"  ├─ Total Pips      : {total_pips:+.1f}")
print(f"  └─ Net P&L         : ${total_pnl:+.2f}")
print()
print(f"  {'SCALP TRADES':}")
print(f"  ├─ Wins            : {scalp_wins}")
print(f"  ├─ Losses          : {scalp_losses}")
print(f"  ├─ Total Pips      : {scalp_pips:+.1f}")
print(f"  └─ Net P&L         : ${scalp_pnl:+.2f}")
print()
print(f"  {'TCP / TREND TRADES':}")
print(f"  ├─ Wins            : {tcp_wins}")
print(f"  ├─ Losses          : {tcp_losses}")
print(f"  ├─ Total Pips      : {tcp_pips:+.1f}")
print(f"  └─ Net P&L         : ${tcp_pnl:+.2f}")
print()

# ── CONTEXT: What was market doing? ──────────────────────────────────────────
print(f"  {'MARKET CONTEXT (Today\'s Range on H1)':}")
try:
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 24)
    import pandas as pd
    mdf = pd.DataFrame(rates)
    day_high = float(mdf['high'].max())
    day_low  = float(mdf['low'].min())
    day_range = round(day_high - day_low, 2)
    # Overall direction
    day_open  = float(mdf['open'].iloc[0])
    day_close = float(mdf['close'].iloc[-1])
    day_dir   = "BULLISH ▲" if day_close > day_open else "BEARISH ▼"
    print(f"  ├─ Day High        : {day_high}")
    print(f"  ├─ Day Low         : {day_low}")
    print(f"  ├─ Day Range       : {day_range} pts")
    print(f"  └─ Day Direction   : {day_dir} (open {day_open:.2f} → close {day_close:.2f})")
except Exception as e:
    print(f"  └─ Could not fetch market data: {e}")

print(f"\n{'='*80}\n")
