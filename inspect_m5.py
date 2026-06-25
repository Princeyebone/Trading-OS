from sqlmodel import select
from engine.db import get_session
from app.models.trades import Trade
import MetaTrader5 as mt5

def inspect():
    session = get_session()
    
    # Get the trade we injected
    t = session.exec(select(Trade).where(Trade.broker_order_id == "152257042645")).first()
    
    if not t:
        print("Trade 152257042645 not found in DB!")
        return
        
    print(f"--- DATABASE RECORD ---")
    print(f"ID: {t.id}")
    print(f"Status: {t.status}")
    print(f"Direction: {t.direction}")
    print(f"Planned Entry: {t.planned_entry}")
    print(f"Highest Profit (pips): {t.highest_profit_pips}")
    print(f"Locked Profit (pips): {t.locked_profit_pips}")
    
    mt5.initialize()
    
    print("\n--- MT5 ACTIVE POSITIONS ---")
    pos = mt5.positions_get(ticket=int(t.broker_order_id))
    if pos:
        p = pos[0]
        print(f"Still Open! Current Profit: {p.profit}, SL: {p.sl}, Current Price: {p.price_current}")
    else:
        print("Not open in MT5.")
        
    print("\n--- MT5 HISTORY DEALS ---")
    deals = mt5.history_deals_get(position=int(t.broker_order_id))
    if deals:
        for d in deals:
            print(f"Deal {d.ticket}: Entry/Exit={d.entry}, Price={d.price}, Profit={d.profit}, Time={d.time}, Reason={d.reason}")
            
inspect()
