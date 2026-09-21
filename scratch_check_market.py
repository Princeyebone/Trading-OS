import MetaTrader5 as mt5
from datetime import datetime

def check_market():
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return

    symbols = ["EURUSD", "XAUUSD"]
    
    for sym in symbols:
        info = mt5.symbol_info(sym)
        if info is None:
            print(f"{sym} not found, can not check market")
            continue
            
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            print(f"{sym} no ticks available")
            continue
            
        print(f"--- {sym} ---")
        print(f"Market Open: {info.session_deals == 1 or info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL}")
        print(f"Last Tick Time (MT5): {datetime.fromtimestamp(tick.time)}")
        
    mt5.shutdown()

if __name__ == "__main__":
    check_market()
