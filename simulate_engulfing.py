"""
simulate_engulfing.py
Tests an Engulfing Continuation strategy for strong momentum days.
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
    # Test 30 days
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
    
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_date, now)
    h4_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H4, start_date - timedelta(days=30), now)
    
    m5_df = pd.DataFrame(m5_rates)
    h4_df = pd.DataFrame(h4_rates)
    
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    h4_df['time'] = pd.to_datetime(h4_df['time'], unit='s', utc=True)
    
    m5_df['ema_20'] = ta.trend.ema_indicator(m5_df['close'], window=20)
    m5_df['ema_50'] = ta.trend.ema_indicator(m5_df['close'], window=50)
    
    SL_DIST = 12.0
    TP_DIST = 20.0
    
    total_pnl = 0.0
    wins, losses, scratches = 0, 0, 0
    trades_taken = 0
    last_trade_time = start_date

    print(f"Running Engulfing Continuation Backtest: 30 Days")
    print("="*100)

    for i in range(50, len(m5_df)):
        curr = m5_df.iloc[i]
        prev = m5_df.iloc[i-1]
        curr_ts = curr['time']
        
        if (curr_ts - last_trade_time).total_seconds() < 1800:
            continue
            
        ema20 = curr['ema_20']
        ema50 = curr['ema_50']
        current_price = curr['close']
        
        # Must be trending
        ema_spread = abs(ema20 - ema50)
        if ema_spread < 1.0: 
            continue
            
        h4_trend = get_h4_trend(h4_df, curr_ts)
        direction = None
        
        # Engulfing LONG
        if ema20 > ema50 and h4_trend == "BULLISH":
            # Prev candle RED
            if prev['close'] < prev['open']:
                # Current candle GREEN and Engulfs
                if curr['close'] > curr['open'] and curr['close'] > prev['high']:
                    # Ensure price is above EMA20 (we are in a trend, not a reversal)
                    if current_price > ema20:
                        direction = "LONG"
                        
        # Engulfing SHORT
        elif ema20 < ema50 and h4_trend == "BEARISH":
            # Prev candle GREEN
            if prev['close'] > prev['open']:
                # Current candle RED and Engulfs
                if curr['close'] < curr['open'] and curr['close'] < prev['low']:
                    if current_price < ema20:
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
                    if l <= current_price - SL_DIST: pnl = -SL_DIST; result_str = "LOSS"; break
                    if h >= current_price + TP_DIST: pnl = TP_DIST; result_str = "WIN"; break
                else:
                    if h >= current_price + SL_DIST: pnl = -SL_DIST; result_str = "LOSS"; break
                    if l <= current_price - TP_DIST: pnl = TP_DIST; result_str = "WIN"; break
                    
        total_pnl += pnl
        if result_str == "WIN": wins += 1
        elif result_str == "LOSS": losses += 1
        else: scratches += 1

    print("="*100)
    print(f"ENGULFING CONTINUATION RESULTS (30 Days)")
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
