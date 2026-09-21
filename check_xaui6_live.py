from sqlmodel import select
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome
from app.models.signals import Signal

session = get_session()
xau_i6_trades = session.exec(select(Trade).where(Trade.system == 'XAUI6').order_by(Trade.opened_at.desc())).all()
print(f"Total live trades fired by new XAUI6 system: {len(xau_i6_trades)}")

for t in xau_i6_trades:
    o = session.exec(select(TradeOutcome).where(TradeOutcome.trade_id == t.id)).first()
    pnl = f"${o.pnl_dollars:.2f} ({o.pnl_pips:.1f} pips)" if o and o.pnl_dollars is not None else "OPEN"
    exit_r = o.exit_reason if o else "N/A"
    open_str = t.opened_at.strftime('%H:%M:%S UTC')
    close_str = t.closed_at.strftime('%H:%M:%S UTC') if t.closed_at else "OPEN"
    print(f"Trade #{t.id} | Ticket: {t.broker_order_id} | Dir: {t.direction} | Opened: {open_str} | Closed: {close_str} | Status: {t.status} | PnL: {pnl} | Exit: {exit_r}")
