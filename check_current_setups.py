import MetaTrader5 as mt5
from datetime import datetime, timezone
import pandas as pd
from engine.scalping_engine import ScalpingEngine

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return
        
    # Fetch enough data to populate indicators
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 200)
    rates_m15 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M15, 0, 200)
    rates_m1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 200)
    
    if rates is None or len(rates) == 0:
        print("No MT5 data.")
        return
        
    df5 = pd.DataFrame(rates)
    df5['time'] = pd.to_datetime(df5['time'], unit='s', utc=True)
    
    df15 = pd.DataFrame(rates_m15)
    df15['time'] = pd.to_datetime(df15['time'], unit='s', utc=True)
    
    df1 = pd.DataFrame(rates_m1)
    df1['time'] = pd.to_datetime(df1['time'], unit='s', utc=True)
    
    engine = ScalpingEngine(df5, df15)
    
    # Check last 3 closed M5 candles
    print("Checking for setups on recent closed candles:")
    for i in range(len(df5)-4, len(df5)):
        candle_time = df5['time'].iloc[i].strftime('%H:%M')
        signals = engine.scan(i, h4_trend="UNKNOWN")
        print(f"Candle {candle_time}: {len(signals)} setups detected.")
        for sig in signals:
            print(f"  -> {sig['type']} | {sig['direction']} | {sig['price']}")
            
    print("\nChecking for setups on recent closed M1 candles:")
    # We must pass M1 data directly to engine property or method if required, 
    # but let's just use detect_m1_ema_pullback_scalp directly since engine doesn't store df1 natively.
    from engine.scalping_engine import detect_m1_ema_pullback_scalp
    for i in range(len(df1)-4, len(df1)):
        candle_time = df1['time'].iloc[i].strftime('%H:%M')
        dir_, det_ = detect_m1_ema_pullback_scalp(df1, i, h4_trend="UNKNOWN")
        if dir_:
            print(f"M1 Candle {candle_time}: 1 setup detected.")
            print(f"  -> M1_EMA_PULLBACK | {dir_}")
        else:
            print(f"M1 Candle {candle_time}: 0 setups detected.")
            
    mt5.shutdown()

if __name__ == "__main__":
    run()
