import MetaTrader5 as mt5
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

print(f"Connecting to {server} with login {login}")

if not mt5.initialize(login=login, password=password, server=server):
    print("initialize() failed, error code =", mt5.last_error())
else:
    print("MT5 initialized successfully")
    info = mt5.terminal_info()
    if info:
        print("Terminal Info:", info)
    
    account_info = mt5.account_info()
    if account_info:
        print("Account Info:", account_info)
    else:
        print("Failed to get account info, error code =", mt5.last_error())

    mt5.shutdown()
