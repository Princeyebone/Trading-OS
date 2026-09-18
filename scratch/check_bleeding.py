import sys
import os
import MetaTrader5 as mt5

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine.db import get_session
from app.models.trades import Trade
from engine.broker_executor import _init_mt5

def check_bleeding():
    _init_mt5()
    session = get_session()
    print("=== CURRENT OPEN TRADES ===")
        
    from sqlmodel import select
    open_trades = session.exec(select(Trade).where(Trade.status == 'OPEN')).all()
    for t in open_trades:
        p = pos_map.get(t.broker_order_id)
        if p:
            profit_pips = p.profit # This is in dollars, need points
            points = (p.price_current - p.price_open) if p.type == 0 else (p.price_open - p.price_current)
            pips = points * 10
            print(f"Trade #{t.id} [{t.system or 'Unknown'}] {t.direction} @ {t.actual_entry} | Current: {p.price_current} | PnL: {pips:.1f} pips (${p.profit:.2f})")
        else:
            print(f"Trade #{t.id} [{t.system or 'Unknown'}] is OPEN in DB but MISSING in MT5")

if __name__ == "__main__":
    check_bleeding()
