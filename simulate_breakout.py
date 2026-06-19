"""
simulate_breakout.py
Simulates a new 'H4 Trend Breakout' module on today's M5 data.
Logic:
1. Identify consolidation over the last 6-8 M5 candles (tight high/low range).
2. Wait for an M5 candle to close strongly outside this range in the direction of the H4 trend.
3. Apply 120-pip max SL and simulate forward.
"""

import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta

def get_h4_trend(h4_df, current_ts):
    df = h4_df[h4_df['time'] <= current_ts]
    if len(df) < 50: return "UNKNOWN"
    ema20 = ta.trend.ema_indicator(df["close"].astype(float), window=20).iloc[-1]
    ema50 = ta.trend.ema_indicator(df["close"].astype(float), window=50).iloc[-1]
    if ema20 > ema50: return "BULLISH"
    if ema20 < ema50: return "BEARISH"
    return "MIXED"

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_of_day - timedelta(days=1), now)
    h4_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H4, start_of_day - timedelta(days=30), now)
    
    m5_df = pd.DataFrame(m5_rates)
    h4_df = pd.DataFrame(h4_rates)
    
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    h4_df['time'] = pd.to_datetime(h4_df['time'], unit='s', utc=True)
    
    today_m5 = m5_df[m5_df['time'] >= start_of_day].copy().reset_index(drop=True)
    
    # Parameters for Breakout
    LOOKBACK = 6         # 30 minutes of consolidation
    MAX_BOX_SIZE = 10.0  # 100 pips max box size
    SL_DIST = 12.0       # 120 pips max SL
    TP_DIST = 20.0       # 200 pips target
    
    total_pnl = 0.0
    wins = 0
    trades_taken = 0

    print("\n" + "="*110)
    print(f"{'Time':<20} | {'Type':<5} | {'Entry':<10} | {'Box Size':<10} | {'PnL':<10} | {'Result'}")
    print("="*110)

    for i in range(LOOKBACK, len(today_m5)):
        curr = today_m5.iloc[i]
        curr_ts = curr['time']
        
        # Define the consolidation box
        box_window = today_m5.iloc[i-LOOKBACK:i]
        box_high = float(box_window['high'].max())
        box_low = float(box_window['low'].min())
        box_size = box_high - box_low
        
        # Check if consolidation is tight enough
        if box_size > MAX_BOX_SIZE:
            continue
            
        h4_trend = get_h4_trend(h4_df, curr_ts)
        direction = None
        entry_price = float(curr['close'])
        
        # Breakout LONG
        if entry_price > box_high and h4_trend == "BULLISH":
            direction = "LONG"
            
        # Breakout SHORT
        elif entry_price < box_low and h4_trend == "BEARISH":
            direction = "SHORT"
            
        if not direction:
            continue
            
        trades_taken += 1
        
        # Simulate forward
        end_ts = curr_ts + timedelta(hours=4)
        m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, curr_ts, end_ts)
        
        pnl = 0.0
        result_str = "TIMEOUT"
        
        if m1_rates is not None and len(m1_rates) > 0:
            m1_df = pd.DataFrame(m1_rates)
            for _, row in m1_df.iterrows():
                h, l = row["high"], row["low"]
                if direction == "LONG":
                    if l <= entry_price - SL_DIST: pnl = -SL_DIST; result_str = "LOSS"; break
                    if h >= entry_price + TP_DIST: pnl = TP_DIST; result_str = "WIN"; break
                else:
                    if h >= entry_price + SL_DIST: pnl = -SL_DIST; result_str = "LOSS"; break
                    if l <= entry_price - TP_DIST: pnl = TP_DIST; result_str = "WIN"; break
                    
        total_pnl += pnl
        if pnl > 0: wins += 1
        
        print(f"{curr_ts.strftime('%H:%M:%S'):<20} | {direction:<5} | {entry_price:<10.2f} | {box_size:<10.2f} | {pnl:>8.2f} | {result_str}")
        
        # Skip forward a bit to avoid duplicate signals for the same breakout
        # Wait, in a simple loop we might trigger 3 candles in a row. 
        # For this test, we'll just log all of them to see raw hit rate.

    print("="*110)
    print(f"H4 Breakout Module : Net {total_pnl:+.2f} pts | Wins: {wins}/{trades_taken}")
    print("="*110)

if __name__ == "__main__":
    run()
