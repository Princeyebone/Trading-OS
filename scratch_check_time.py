import MetaTrader5 as mt5
from datetime import datetime

def check_time():
    if not mt5.initialize():
        print("initialize() failed")
        return
        
    info = mt5.terminal_info()
    if info is not None:
        print(f"Terminal Connected: {info.connected}")
        print(f"Trade Allowed: {info.trade_allowed}")
        
    # Get symbols
    for sym in ["EURUSD", "XAUUSD"]:
        tick = mt5.symbol_info_tick(sym)
        if tick:
            print(f"{sym} Last Tick: {datetime.fromtimestamp(tick.time)} (MT5 Server Time: {tick.time_msc})")
            
    mt5.shutdown()

if __name__ == "__main__":
    check_time()
