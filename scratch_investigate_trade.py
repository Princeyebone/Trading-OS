import sys
import os
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

MAGIC_MAP = {
    202600: "XAGI1",  202601: "XAGI1-Swing",
    202602: "XAGI2",  202603: "XAGI3",
    202604: "XAGI4",  202700: "XAGI3",
    202800: "XAGI5",  202900: "XAGI6",
    202808: "XAGI8-IFVG", 202809: "XAGI9-3Candle",
    203000: "EUSDI6", 203100: "EUSDI7",
    203200: "GI2",    203300: "GI3",
}

start_time = datetime.now() - timedelta(hours=6)
deals = mt5.history_deals_get(start_time, datetime.now() + timedelta(days=1))

if not deals:
    print("No deals found.")
    sys.exit(0)

print("Looking for deals around $2.88...\n")
for deal in deals:
    if deal.entry == 1: # OUT deal (closing)
        total_profit = deal.profit + deal.commission + deal.swap
        if 2.50 <= total_profit <= 3.20 or 2.50 <= deal.profit <= 3.20:
            magic = deal.magic
            strat = MAGIC_MAP.get(magic, f"UNKNOWN_{magic}")
            time_str = datetime.fromtimestamp(deal.time, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            print(f"Match Found! Ticket: {deal.ticket} | Symbol: {deal.symbol}")
            print(f"Strategy: {strat} (Magic: {magic}) | Comment: {deal.comment}")
            print(f"Close Time: {time_str}")
            print(f"Volume: {deal.volume}")
            print(f"Price: {deal.price}")
            print(f"Raw Profit: ${deal.profit:.2f} | Commission: ${deal.commission:.2f} | Swap: ${deal.swap:.2f}")
            print(f"Total Net PnL: ${total_profit:.2f}\n")

mt5.shutdown()
