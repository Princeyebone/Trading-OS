"""
Full trade analysis for today after 08:30 MT5 time.
Combines DB records with MT5 deal history for accurate PnL.
"""
import sys, os
sys.path.insert(0, r'C:\Users\HP\OneDrive\Desktop\tb\backend')
os.chdir(r'C:\Users\HP\OneDrive\Desktop\tb\backend')

from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5
from sqlmodel import select, Session
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome
from app.models.signals import Signal

mt5.initialize()

# ── Cutoff: 08:30 UTC (which is 09:30 London / MT5 is UTC+3 so 11:30 MT5 server)
# User said 8:30am - we'll treat as 07:30 UTC to be safe and catch everything
cutoff_utc = datetime(2026, 6, 30, 7, 30, 0, tzinfo=timezone.utc)

session = get_session()

# Pull all trades opened after 8:30
all_trades = session.exec(
    select(Trade).where(Trade.opened_at >= cutoff_utc).order_by(Trade.opened_at)
).all()

print(f"Found {len(all_trades)} trades after 08:30 UTC\n")

# Pull MT5 deal history for today
start = datetime(2026, 6, 30, 0, 0, 0, tzinfo=timezone.utc)
end   = datetime.now(timezone.utc)
deals = mt5.history_deals_get(start, end)
deal_map = {}  # position_id -> list of deals
if deals:
    for d in deals:
        pos_id = str(d.position_id)
        if pos_id not in deal_map:
            deal_map[pos_id] = []
        deal_map[pos_id].append(d)

# Build system map
MAGIC_MAP = {
    202600: "XAGI1",  202601: "XAGI1-Swing",
    202602: "XAGI2-FVG",  202603: "XAGI3-M5Runner",
    202604: "XAGI4-M15Runner",  202700: "XAGI3-Tape",
    202800: "XAGI5",  202900: "XAGI6",
    203000: "EUSDI6", 203100: "EUSDI7",
    203200: "GI2",    203300: "GI3",
}

rows = []
for trade in all_trades:
    if not trade.broker_order_id:
        continue

    sig = session.get(Signal, trade.signal_id) if trade.signal_id else None
    sys_name = sig.session if (sig and sig.session) else None

    # Try MT5 history
    ticket = trade.broker_order_id
    trade_deals = deal_map.get(ticket, [])
    
    # Get entry deal
    entry_deal = next((d for d in trade_deals if d.entry == 0), None)
    exit_deal  = next((d for d in trade_deals if d.entry == 1), None)

    symbol = "?"
    magic  = 0
    if entry_deal:
        symbol = entry_deal.symbol
        magic  = entry_deal.magic
    
    if not sys_name:
        sys_name = MAGIC_MAP.get(magic, f"M#{magic}")

    actual_profit = exit_deal.profit if exit_deal else None
    exit_price    = exit_deal.price  if exit_deal else None
    entry_price   = entry_deal.price if entry_deal else trade.actual_entry or trade.planned_entry

    # Pip calc
    try:
        sinfo = mt5.symbol_info(symbol)
        pip_mult = 1.0 / (sinfo.point * 10.0) if sinfo and sinfo.point else 10.0
    except:
        pip_mult = 10.0

    if actual_profit is not None and entry_price and exit_price:
        if trade.direction == "LONG":
            pips = (exit_price - entry_price) * pip_mult
        else:
            pips = (entry_price - exit_price) * pip_mult
    else:
        # Still open — get live price
        pos = mt5.positions_get(ticket=int(ticket))
        if pos:
            tick = mt5.symbol_info_tick(pos[0].symbol)
            symbol = pos[0].symbol
            magic = pos[0].magic
            if not sys_name or sys_name.startswith("M#"):
                sys_name = MAGIC_MAP.get(magic, f"M#{magic}")
            live = tick.bid if trade.direction == "SHORT" else tick.ask
            pips = (entry_price - live) * pip_mult if trade.direction == "SHORT" else (live - entry_price) * pip_mult
            actual_profit = pos[0].profit
            exit_price = None  # still open
        else:
            pips = 0.0

    opened_str = trade.opened_at.strftime("%H:%M:%S") if trade.opened_at else "?"
    closed_str = trade.closed_at.strftime("%H:%M:%S") if trade.closed_at else "OPEN"

    rows.append({
        "id":      trade.id,
        "ticket":  ticket,
        "system":  sys_name,
        "symbol":  symbol,
        "dir":     trade.direction,
        "opened":  opened_str,
        "closed":  closed_str,
        "status":  trade.status,
        "entry":   entry_price,
        "exit":    exit_price,
        "pips":    round(pips, 1),
        "profit":  round(actual_profit, 2) if actual_profit is not None else None,
        "lot":     trade.lot_size,
    })

# ── Print table ──
print(f"{'ID':>5} {'Ticket':>15} {'System':>18} {'Sym':>7} {'Dir':>5} {'Opened':>9} {'Closed':>9} {'Status':>10} {'Entry':>9} {'Exit':>9} {'Pips':>8} {'$PnL':>8} {'Lot':>5}")
print("-" * 140)

for r in rows:
    entry_str  = f"{r['entry']:.5f}" if r['entry'] and r['entry'] < 10 else (f"{r['entry']:.2f}" if r['entry'] else "?")
    exit_str   = f"{r['exit']:.5f}"  if r['exit']  and r['exit']  < 10 else (f"{r['exit']:.2f}"  if r['exit']  else "OPEN")
    profit_str = f"${r['profit']:+.2f}" if r['profit'] is not None else "?"
    pips_str   = f"{r['pips']:+.1f}" if r['pips'] else "?"
    print(f"{r['id']:>5} {r['ticket']:>15} {r['system']:>18} {r['symbol']:>7} {r['dir']:>5} {r['opened']:>9} {r['closed']:>9} {r['status']:>10} {entry_str:>9} {exit_str:>9} {pips_str:>8} {profit_str:>8} {r['lot']:>5}")

# ── Summary by system ──
print("\n" + "="*60)
print("SUMMARY BY SYSTEM")
print("="*60)
from collections import defaultdict
by_sys = defaultdict(lambda: {"wins":0,"losses":0,"pnl":0.0,"pips":0.0,"open":0})
for r in rows:
    s = r["system"]
    if r["status"] == "WIN":
        by_sys[s]["wins"] += 1
        by_sys[s]["pnl"]  += r["profit"] or 0
        by_sys[s]["pips"] += r["pips"] or 0
    elif r["status"] == "LOSS":
        by_sys[s]["losses"] += 1
        by_sys[s]["pnl"]    += r["profit"] or 0
        by_sys[s]["pips"]   += r["pips"] or 0
    elif r["status"] == "OPEN":
        by_sys[s]["open"] += 1
        by_sys[s]["pnl"]  += r["profit"] or 0
        by_sys[s]["pips"] += r["pips"] or 0

total_pnl = 0.0
print(f"\n{'System':>18} {'Wins':>5} {'Losses':>7} {'Open':>5} {'Total $PnL':>12} {'Total Pips':>12}")
print("-"*65)
for sys_name, d in sorted(by_sys.items()):
    total_pnl += d["pnl"]
    wr = d["wins"]/(d["wins"]+d["losses"]) * 100 if (d["wins"]+d["losses"]) > 0 else 0
    print(f"{sys_name:>18} {d['wins']:>5} {d['losses']:>7} {d['open']:>5} ${d['pnl']:>+10.2f} {d['pips']:>+10.1f} pips  (WR:{wr:.0f}%)")

print(f"\n{'TOTAL':>18} {'':>5} {'':>7} {'':>5} ${total_pnl:>+10.2f}")

# ── Active positions snapshot ──
open_rows = [r for r in rows if r["status"] == "OPEN"]
if open_rows:
    print(f"\n{'='*60}")
    print("CURRENTLY OPEN POSITIONS")
    print("="*60)
    for r in open_rows:
        entry_str = f"{r['entry']:.5f}" if r['entry'] and r['entry'] < 10 else (f"{r['entry']:.2f}" if r['entry'] else "?")
        print(f"  Trade #{r['id']} | {r['system']:>18} | {r['symbol']} {r['dir']} | Entry: {entry_str} | Live PnL: {r['pips']:+.1f} pips (${r['profit']:+.2f}) | Ticket: {r['ticket']}")
