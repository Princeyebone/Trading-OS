import sys
import os
import MetaTrader5 as mt5
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

ticket = 58154574385
deal = mt5.history_deals_get(ticket=ticket)

if not deal:
    print(f"Deal {ticket} not found.")
else:
    deal = deal[0]
    print(f"--- DEAL TICKET {ticket} ---")
    print(f"Symbol: {deal.symbol}")
    print(f"Action: {'BUY' if deal.type == mt5.DEAL_TYPE_BUY else 'SELL'}")
    print(f"Entry/Exit: {'IN' if deal.entry == 0 else 'OUT'}")
    print(f"Volume: {deal.volume}")
    print(f"Price: {deal.price}")
    print(f"Commission: {deal.commission}")
    print(f"Swap: {deal.swap}")
    print(f"Profit: {deal.profit}")
    print(f"Comment: {deal.comment}")
    
    pos_id = deal.position_id
    print(f"\n--- POSITION HISTORY (ID: {pos_id}) ---")
    pos_deals = mt5.history_deals_get(position=pos_id)
    if pos_deals:
        for d in pos_deals:
            time_str = datetime.fromtimestamp(d.time, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            print(f"[{time_str}] Deal {d.ticket}: {'IN' if d.entry==0 else 'OUT'} {'BUY' if d.type==0 else 'SELL'} @ {d.price} | Profit: {d.profit} | Comment: {d.comment}")
            
mt5.shutdown()
