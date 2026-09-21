import sys
import os
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

account_info = mt5.account_info()
if account_info:
    print(f"Balance: {account_info.balance}")
    print(f"Currency: {account_info.currency}")
    print(f"Equity: {account_info.equity}")
    print(f"Leverage: 1:{account_info.leverage}")
else:
    print("Failed to get account info")

mt5.shutdown()
