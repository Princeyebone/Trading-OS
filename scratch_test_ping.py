import MetaTrader5 as mt5
import os
import time
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    exit(1)

print("Testing MT5 network latency (ping) over 5 seconds...")
for i in range(5):
    info = mt5.terminal_info()
    if info:
        ping_ms = info.ping_last / 1000.0
        print(f"Ping {i+1}: {ping_ms:.2f} ms")
    time.sleep(1)

mt5.shutdown()
