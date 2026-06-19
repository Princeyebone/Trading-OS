"""
simulate_flag.py
Tests an M5 Flag (Micro-Consolidation Breakout) strategy for strong momentum days.
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
    
    SL_DIST = 12.0
    TP_DIST = 20.0
    
    total_pnl = 0.0
    wins, losses, scratches = 0, 0, 0
    trades_taken = 0
    last_trade_time = start_date

    print(f"Running M5 Flag Backtest: 30 Days")
    print("="*100)

    for i in range(50, len(m5_df)):
        curr = m5_df.iloc[i]
        curr_ts = curr['time']
        
        if (curr_ts - last_trade_time).total_seconds() < 1800:
            continue
            
        ema20 = curr['ema_20']
        current_price = curr['close']
        
        h4_trend = get_h4_trend(h4_df, curr_ts)
        direction = None
        
        # We need a 4-candle sequence: 
        # Candle 1: Impulse (Large body, strong momentum)
        # Candle 2 & 3: Consolidation (Small bodies, stay within Candle 1's range or slightly retrace)
        # Candle 4 (Current): Breakout of the consolidation
        
        impulse = m5_df.iloc[i-3]
        pause1 = m5_df.iloc[i-2]
        pause2 = m5_df.iloc[i-1]
        
        impulse_range = impulse['high'] - impulse['low']
        if impulse_range < 2.0: # Not a strong impulse
            continue
            
        # Bear Flag
        if h4_trend == "BEARISH" and current_price < ema20:
            impulse_is_bearish = impulse['close'] < impulse['open']
            
            # The pauses must be relatively small
            pause1_range = pause1['high'] - pause1['low']
            pause2_range = pause2['high'] - pause2['low']
            
            if pause1_range < impulse_range and pause2_range < impulse_range:
                # Pauses must stay above the low of the impulse
                if pause1['low'] > impulse['low'] and pause2['low'] > impulse['low']:
                    # Breakout confirmation
                    if current_price < impulse['low']:
                        direction = "SHORT"
                        
        # Bull Flag
        elif h4_trend == "BULLISH" and current_price > ema20:
            impulse_is_bullish = impulse['close'] > impulse['open']
            
            pause1_range = pause1['high'] - pause1['low']
            pause2_range = pause2['high'] - pause2['low']
            
            if pause1_range < impulse_range and pause2_range < impulse_range:
                if pause1['high'] < impulse['high'] and pause2['high'] < impulse['high']:
                    if current_price > impulse['high']:
                        direction = "LONG"
                        
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
    print(f"M5 FLAG RESULTS (30 Days)")
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
