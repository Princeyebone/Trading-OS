"""
backtest_breakout_historical.py
Runs the H4 Trend Breakout module over the last 14 days to verify parameters.
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
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=14)
    
    # Fetch Data
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_date, now)
    h4_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H4, start_date - timedelta(days=30), now)
    
    m5_df = pd.DataFrame(m5_rates)
    h4_df = pd.DataFrame(h4_rates)
    
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    h4_df['time'] = pd.to_datetime(h4_df['time'], unit='s', utc=True)
    
    # Parameters for Breakout
    LOOKBACK = 6         # 30 minutes of consolidation
    MAX_BOX_SIZE = 10.0  # 100 pips max box size
    SL_DIST = 12.0       # 120 pips max SL
    TP_DIST = 20.0       # 200 pips target
    
    total_pnl = 0.0
    wins = 0
    trades_taken = 0
    losses = 0
    scratches = 0
    
    # We want to prevent overlapping trades (taking 3 breakouts on the same box)
    last_trade_time = start_date

    print(f"Running Historical Backtest: {start_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}")
    print("="*100)

    for i in range(LOOKBACK, len(m5_df)):
        curr = m5_df.iloc[i]
        curr_ts = curr['time']
        
        if (curr_ts - last_trade_time).total_seconds() < 3600:
            continue # Only 1 trade per hour to avoid clustering
            
        # Define the consolidation box
        box_window = m5_df.iloc[i-LOOKBACK:i]
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
        last_trade_time = curr_ts
        
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
        if result_str == "WIN": wins += 1
        elif result_str == "LOSS": losses += 1
        else: scratches += 1
        
        # print(f"{curr_ts.strftime('%Y-%m-%d %H:%M')} | {direction:<5} | {result_str:<7} | {pnl:>+6.2f} pts")

    print("="*100)
    print(f"BACKTEST RESULTS (14 Days)")
    print(f"Total Trades : {trades_taken}")
    print(f"Wins         : {wins}")
    print(f"Losses       : {losses}")
    print(f"Scratches    : {scratches}")
    if trades_taken > 0:
        print(f"Win Rate     : {(wins/trades_taken)*100:.1f}%")
    print(f"Net PnL      : {total_pnl:+.2f} points (+{total_pnl*10:+.0f} pips)")
    print("="*100)

if __name__ == "__main__":
    run()
