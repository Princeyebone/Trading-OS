import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
from sqlmodel import select
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome
from app.models.signals import Signal

mt5.initialize()
now = datetime.now(timezone.utc)
since = now - timedelta(hours=3)

deals = mt5.history_deals_get(since, now)
out_deals = [d for d in deals if d.entry == 1]
out_deals.sort(key=lambda x: x.profit)

print("=== TOP 10 BIGGEST LOSSES IN MT5 (LAST 3 HOURS) ===")
for d in out_deals[:10]:
    dt = datetime.fromtimestamp(d.time, tz=timezone.utc)
    print(f"Deal #{d.ticket} | Time: {dt.strftime('%H:%M:%S UTC')} | Sym: {d.symbol} | Profit: ${d.profit:.2f} | Magic: {d.magic} | Comment: {d.comment}")

print("\n=== CURRENT OPEN POSITIONS IN MT5 ===")
open_pos = mt5.positions_get()
for p in open_pos:
    side = "BUY" if p.type == 0 else "SELL"
    print(f"Pos #{p.ticket} | Sym: {p.symbol} | Dir: {side} | Lots: {p.volume} | Open: {p.price_open} | Cur: {p.price_current} | SL: {p.sl} | TP: {p.tp} | Profit: ${p.profit:.2f} | Magic: {p.magic} | Comment: {p.comment}")
