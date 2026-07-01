import MetaTrader5 as mt5
import pandas as pd
import ta
from datetime import datetime, timedelta, timezone

def test_eusdi6():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return
        
    print("MT5 Connected.")
    
    symbol = "EURUSD"
    # Fetch last 12 hours of M1 data (12 * 60 = 720 bars)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 800)
    if rates is None:
        print("Failed to fetch rates")
        mt5.shutdown()
        return
        
    df = pd.DataFrame(rates)
    df['time_dt'] = pd.to_datetime(df['time'], unit='s')
    
    close_series = df['close']
    bb = ta.volatility.BollingerBands(close_series, window=20, window_dev=2.0)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    df['bb_mid'] = bb.bollinger_mavg()
    df['rsi'] = ta.momentum.rsi(close_series, window=14)
    
    signals = []
    
    for i in range(25, len(df)):
        current = df.iloc[i]
        price = current['close']
        bb_upper = current['bb_upper']
        bb_lower = current['bb_lower']
        rsi = current['rsi']
        
        if price < bb_lower and rsi < 30:
            signals.append((current['time_dt'], "LONG", price, rsi, bb_lower))
        elif price > bb_upper and rsi > 70:
            signals.append((current['time_dt'], "SHORT", price, rsi, bb_upper))
            
    print(f"Total M1 bars processed: {len(df)}")
    print(f"Total signals found: {len(signals)}")
    for s in signals:
        print(f"Time: {s[0]} | Dir: {s[1]} | Price: {s[2]:.5f} | RSI: {s[3]:.1f}")
        
    mt5.shutdown()

if __name__ == "__main__":
    test_eusdi6()
