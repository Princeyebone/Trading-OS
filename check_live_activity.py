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
open_pos = mt5.positions_get()

print("=== CURRENT OPEN POSITIONS IN MT5 ===")
if open_pos:
    for p in open_pos:
        side = "BUY" if p.type == 0 else "SELL"
        print(f"Ticket: {p.ticket} | Sym: {p.symbol} | Dir: {side} | Magic: {p.magic} | Vol: {p.volume} | Open: {p.price_open} | Profit: ${p.profit:.2f} | Comment: {p.comment}")
else:
    print("No open positions in MT5 right now.")

print("\n=== CLOSED DEALS IN LAST 3 HOURS (MT5) ===")
if deals:
    out_deals = [d for d in deals if d.entry == 1]
    print(f"Total exit deals: {len(out_deals)}")
    for d in out_deals:
        dt = datetime.fromtimestamp(d.time, tz=timezone.utc)
        print(f"Ticket: {d.ticket} | Time: {dt.strftime('%H:%M:%S UTC')} | Sym: {d.symbol} | Profit: ${d.profit:.2f} | Magic: {d.magic} | Comment: {d.comment}")
else:
    print("No deals in MT5.")

print("\n=== RECENT DATABASE TRADES (LAST 3 HOURS) ===")
session = get_session()
db_trades = session.exec(select(Trade).where(Trade.opened_at >= since).order_by(Trade.opened_at.desc())).all()
print(f"Total DB trades in last 3 hours: {len(db_trades)}")
for t in db_trades:
    o = session.exec(select(TradeOutcome).where(TradeOutcome.trade_id == t.id)).first()
    pnl = f"${o.pnl_dollars:.2f}" if o and o.pnl_dollars is not None else "Still Open / None"
    print(f"Trade #{t.id} | System: {t.system} | Dir: {t.direction} | Lots: {t.lot_size} | Ticket: {t.broker_order_id} | Status: {t.status} | PnL: {pnl} | Opened: {t.opened_at.strftime('%H:%M:%S UTC')}")
