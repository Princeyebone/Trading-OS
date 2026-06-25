from sqlmodel import select
from engine.db import get_session
from app.models.trades import Trade
import MetaTrader5 as mt5

def check():
    session = get_session()
    trades = session.exec(select(Trade).where(Trade.status.in_(["OPEN", "PENDING"]))).all()
    print(f"Open/Pending Trades in DB: {len(trades)}")
    
    mt5.initialize()
    positions = mt5.positions_get(symbol="XAUUSD")
    
    if positions:
        print(f"MT5 Positions: {len(positions)}")
        for p in positions:
            print(f" - Ticket: {p.ticket}, Magic: {p.magic}, Identifier: {p.identifier}, Profit: {p.profit}")
            
    for t in trades:
        print(f"DB Trade: ID={t.id}, Ticket={t.broker_order_id}, Status={t.status}")

check()
