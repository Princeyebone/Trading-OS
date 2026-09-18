import sys
import os
import pandas as pd
import MetaTrader5 as mt5

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine.broker_executor import _init_mt5

def analyze_recent_price_action():
    if not _init_mt5():
        print("Failed to init MT5")
        return
        
    symbol = "XAUUSD"
    # Get last 60 M1 candles (1 hour) to cover 09:20 to 10:20 MT5 time roughly, or last 120 (2 hours)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 180)
    if rates is None:
        print("Failed to get rates")
        return
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # We want to analyze specifically around the 09:40 to 10:20 MT5 time window
    # Print the latest time to see what "now" is in MT5 time
    current_mt5_time = df.iloc[-1]['time']
    print(f"Current MT5 Time of last candle: {current_mt5_time}")
    
    # Let's slice the last 60 minutes
    recent_df = df.iloc[-60:]
    start_time = recent_df.iloc[0]['time']
    end_time = recent_df.iloc[-1]['time']
    
    high_price = recent_df['high'].max()
    low_price = recent_df['low'].min()
    open_price = recent_df.iloc[0]['open']
    close_price = recent_df.iloc[-1]['close']
    
    print(f"\n=== M1 PRICE ACTION ANALYSIS ({start_time} to {end_time}) ===")
    print(f"Open: {open_price:.2f} | Close: {close_price:.2f} | Net Move: {close_price - open_price:+.2f}")
    print(f"High: {high_price:.2f} | Low: {low_price:.2f} | Range: {high_price - low_price:.2f} pts")
    
    # Let's find the biggest volume spikes
    avg_vol = recent_df['tick_volume'].mean()
    vol_spikes = recent_df[recent_df['tick_volume'] > avg_vol * 1.5]
    
    print(f"\nAverage M1 Volume: {avg_vol:.1f}")
    if not vol_spikes.empty:
        print(f"Volume Spikes Detected:")
        for idx, row in vol_spikes.iterrows():
            candle_type = "BULLISH" if row['close'] > row['open'] else "BEARISH"
            print(f"  - {row['time']}: {candle_type} (Vol: {row['tick_volume']}) | Range: {row['high'] - row['low']:.2f} pts")
            
    # Trend Analysis
    ema20 = df['close'].rolling(20).mean().iloc[-1]
    ema50 = df['close'].rolling(50).mean().iloc[-1]
    
    print(f"\nTrend Indicators (End of Period):")
    print(f"Current Price: {close_price:.2f}")
    print(f"EMA20: {ema20:.2f}")
    print(f"EMA50: {ema50:.2f}")
    
    if close_price > ema20 > ema50:
        print("Status: Strong Bullish Trend")
    elif close_price < ema20 < ema50:
        print("Status: Strong Bearish Trend")
    else:
        print("Status: Choppy / Sideways / Consolidating")
        
    print("\n=== RAW DATA FOR LAST 30 MINS ===")
    print(df.tail(30)[['time', 'open', 'high', 'low', 'close', 'tick_volume']].to_string(index=False))

if __name__ == "__main__":
    analyze_recent_price_action()
