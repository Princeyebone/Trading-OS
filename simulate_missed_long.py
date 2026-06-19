import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import pandas as pd

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return
        
    now = datetime.now(timezone.utc)
    # Fetch the last 30 candles directly by index to bypass timezone issues
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 30)
    
    if rates is None or len(rates) == 0:
        print("No M1 data available since 08:30.")
        return
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    
    entry_price = 4175.84
    
    highest = df['high'].max()
    lowest = df['low'].min()
    
    print("="*60)
    print("SIMULATION OF MISSED 08:30 TCP LONG")
    print(f"Entry Price: {entry_price}")
    print(f"Highest Price Reached: {highest:.2f} (+{(highest - entry_price):.2f} pts)")
    print(f"Lowest Price Reached: {lowest:.2f} (-{(entry_price - lowest):.2f} pts)")
    print("="*60)
    
    # Simulate Tight Harvest (1.0 pt)
    tight_locked = False
    tight_win = False
    for i in range(len(df)):
        h, l = df['high'].iloc[i], df['low'].iloc[i]
        if h >= entry_price + 1.0 and not tight_locked:
            tight_locked = True
            print(f"[Tight 10-pip Harvest] Reached +1.0 pts at {df['time'].iloc[i].strftime('%H:%M')}! Profit locked at +0.0 (BE).")
        if tight_locked and l <= entry_price:
            print(f"[Tight 10-pip Harvest] Stopped out at BE.")
            tight_win = True # Technically a BE scratch or small win
            break
            
    # Simulate Wide Harvest (3.0 pt)
    wide_locked = False
    for i in range(len(df)):
        h, l = df['high'].iloc[i], df['low'].iloc[i]
        if h >= entry_price + 3.0 and not wide_locked:
            wide_locked = True
            print(f"[Wide 30-pip Harvest] Reached +3.0 pts at {df['time'].iloc[i].strftime('%H:%M')}! Profit locked at +1.0 pts.")
        if wide_locked and l <= entry_price + 1.0:
            print(f"[Wide 30-pip Harvest] Stopped out at +1.0 pts.")
            break
            
    if not tight_locked:
        print("[Tight 10-pip Harvest] Never reached 1.0 pts.")
    if not wide_locked:
        print("[Wide 30-pip Harvest] Never reached 3.0 pts.")
        
    mt5.shutdown()

if __name__ == "__main__":
    run()
