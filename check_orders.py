from engine.db import get_session
from app.models.trades import Trade
import MetaTrader5 as mt5

def check():
    mt5.initialize()
    
    print("--- ACTIVE POSITIONS ---")
    pos = mt5.positions_get(symbol="XAUUSD")
    if pos:
        for p in pos:
            print(f"Ticket: {p.ticket}, Type: {'BUY' if p.type==0 else 'SELL'}, Magic: {p.magic}, Open: {p.price_open}, Current: {p.price_current}, Profit: {p.profit}")
    else:
        print("No active positions.")
        
    print("\n--- PENDING ORDERS ---")
    orders = mt5.orders_get(symbol="XAUUSD")
    if orders:
        for o in orders:
            type_str = "BUY_LIMIT" if o.type == mt5.ORDER_TYPE_BUY_LIMIT else ("SELL_LIMIT" if o.type == mt5.ORDER_TYPE_SELL_LIMIT else str(o.type))
            print(f"Ticket: {o.ticket}, Type: {type_str}, Magic: {o.magic}, Price: {o.price_open}")
    else:
        print("No pending orders.")

check()
