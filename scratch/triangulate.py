import MetaTrader5 as mt5
from datetime import datetime, timezone
import time

def triangulate():
    if not mt5.initialize():
        return
        
    ticket = 152272051772
    
    # Get that specific deal by ticket (if we can find it)
    deals = mt5.history_deals_get(ticket=ticket)
    if not deals:
        print(f"Could not find ticket {ticket}")
        
        # Try to find by time range
        deals = mt5.history_deals_get(datetime(2026, 6, 29), datetime.now())
        for d in deals:
            if d.position_id == ticket or d.ticket == ticket:
                deals = (d,)
                break
                
    if deals:
        deal = deals[0]
        
        print(f"--- Triangulating Ticket {ticket} ---")
        print(f"deal.time (int): {deal.time}")
        print(f"deal.time_msc: {deal.time_msc}")
        
        utc_dt = datetime.fromtimestamp(deal.time, tz=timezone.utc)
        print(f"UTC datetime: {utc_dt}")
        
        naive_dt = datetime.fromtimestamp(deal.time)
        print(f"Naive local datetime: {naive_dt}")
        
    # Get current MT5 server time
    tick = mt5.symbol_info_tick("EURUSD")
    if tick:
        print("\n--- Current Time ---")
        print(f"MT5 EURUSD tick time: {tick.time}")
        print(f"MT5 tick UTC datetime: {datetime.fromtimestamp(tick.time, tz=timezone.utc)}")
    
    print(f"Python time.time(): {time.time()}")
    print(f"Python naive now(): {datetime.now()}")
    print(f"Python UTC now(): {datetime.now(timezone.utc)}")

    mt5.shutdown()

if __name__ == "__main__":
    triangulate()
