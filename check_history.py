import MetaTrader5 as mt5
from datetime import datetime

def check_history():
    if not mt5.initialize():
        print("MT5 init failed")
        return
        
    date_from = datetime(2025, 1, 1)
    date_to = datetime(2027, 1, 1) # Way in the future to avoid Broker Server time vs Local time offset bugs
    
    deals = mt5.history_deals_get(date_from, date_to)
    
    if not deals:
        print("No deals found at all.")
        return
        
    m15_deals = []
    m5_deals = []
    
    for d in deals:
        if d.magic == 202602:
            m15_deals.append(d)
        elif d.magic == 202603:
            m5_deals.append(d)
            
    print(f"--- M15 SMC RUNNER (Magic 202602) DEALS ---")
    if not m15_deals:
        print("None found.")
    else:
        for d in m15_deals:
            t = "ENTRY" if d.entry == 0 else ("EXIT" if d.entry == 1 else "OTHER")
            print(f"Time: {datetime.fromtimestamp(d.time)}, Ticket: {d.ticket}, Position: {d.position_id}, {t}, Volume: {d.volume}, Price: {d.price}, Profit: {d.profit}, Reason: {d.reason}")
            
    print(f"\n--- M5 MOMENTUM RUNNER (Magic 202603) DEALS ---")
    if not m5_deals:
        print("None found.")
    else:
        for d in m5_deals:
            t = "ENTRY" if d.entry == 0 else ("EXIT" if d.entry == 1 else "OTHER")
            print(f"Time: {datetime.fromtimestamp(d.time)}, Ticket: {d.ticket}, Position: {d.position_id}, {t}, Volume: {d.volume}, Price: {d.price}, Profit: {d.profit}, Reason: {d.reason}")

check_history()
