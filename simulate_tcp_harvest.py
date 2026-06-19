"""
simulate_tcp_harvest.py
Backtests the M15 TCP strategy over 14 days.
Assuming a 4.0 point (40 pip) Take Profit (harvest) and 12.0 point (120 pip) Stop Loss.
It filters out trades that would have gone on to make 30+ points.
"""

import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

from engine.rule_engine import evaluate_all
from engine.data_fetcher import fetch_ohlcv

def get_h4_trend(h4_df, current_ts):
    df = h4_df[h4_df['time'] <= current_ts]
    if len(df) < 50: return "UNKNOWN"
    import ta
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
    
    m15_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M15, start_date - timedelta(days=5), now)
    h1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start_date - timedelta(days=5), now)
    h4_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H4, start_date - timedelta(days=20), now)
    
    m15_df = pd.DataFrame(m15_rates)
    h1_df = pd.DataFrame(h1_rates)
    h4_df = pd.DataFrame(h4_rates)
    
    m15_df['time'] = pd.to_datetime(m15_df['time'], unit='s', utc=True)
    h1_df['time'] = pd.to_datetime(h1_df['time'], unit='s', utc=True)
    h4_df['time'] = pd.to_datetime(h4_df['time'], unit='s', utc=True)
    
    SL_DIST = 12.0
    HARVEST_DIST = 4.0
    
    wins = 0
    losses = 0
    scratches = 0
    total_pnl = 0.0
    trades_taken = 0
    ignored = 0
    
    print("Running TCP 'Harvest at 4pts' Simulation (14 Days)...")
    
    start_idx = m15_df[m15_df['time'] >= start_date].index.min()
    last_trade_time = start_date - timedelta(days=1)
    
    for i in range(start_idx, len(m15_df)-1):
        curr_ts = m15_df['time'].iloc[i]
        
        # 4-hour lockout between TCP trades
        if (curr_ts - last_trade_time).total_seconds() < 14400:
            continue
            
        current_m15 = m15_df.iloc[:i+1].copy()
        current_h1 = h1_df[h1_df['time'] <= curr_ts].copy()
        current_h4 = h4_df[h4_df['time'] <= curr_ts].copy()
        
        timeframes = {
            "M15": current_m15,
            "H1": current_h1,
            "H4": current_h4
        }
        
        signal = evaluate_all(timeframes)
        
        if signal.get('verdict') == 'TRADE':
            # Must pass strict H4 filter or M15 trend filter
            h4_trend = get_h4_trend(h4_df, curr_ts)
            
            direction = signal['direction']
            entry_price = signal['entry']
            
            if direction == 'LONG' and h4_trend == 'BEARISH':
                continue # Blocked
            if direction == 'SHORT' and h4_trend == 'BULLISH':
                continue # Blocked
            
            # Simulate forward using M1 data
            end_ts = curr_ts + timedelta(hours=24)
            m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, curr_ts, end_ts)
            
            if m1_rates is None or len(m1_rates) == 0:
                continue
                
            m1_df = pd.DataFrame(m1_rates)
            mfe_30 = False
            
            # First pass: look for 30+ pt runners
            for _, row in m1_df.iterrows():
                h, l = row["high"], row["low"]
                if direction == "LONG":
                    if l <= entry_price - SL_DIST: break
                    if h >= entry_price + 30.0:
                        mfe_30 = True
                        break
                else:
                    if h >= entry_price + SL_DIST: break
                    if l <= entry_price - 30.0:
                        mfe_30 = True
                        break
                        
            if mfe_30:
                ignored += 1
                last_trade_time = curr_ts
                continue
                
            # Second pass: Harvest at 4.0 pts
            pnl = 0.0
            result_str = "TIMEOUT"
            
            for _, row in m1_df.iterrows():
                h, l = row["high"], row["low"]
                if direction == "LONG":
                    if l <= entry_price - SL_DIST: 
                        pnl = -SL_DIST
                        result_str = "LOSS"
                        break
                    if h >= entry_price + HARVEST_DIST: 
                        pnl = HARVEST_DIST
                        result_str = "WIN"
                        break
                else:
                    if h >= entry_price + SL_DIST: 
                        pnl = -SL_DIST
                        result_str = "LOSS"
                        break
                    if l <= entry_price - HARVEST_DIST: 
                        pnl = HARVEST_DIST
                        result_str = "WIN"
                        break
                        
            trades_taken += 1
            total_pnl += pnl
            if result_str == "WIN": wins += 1
            elif result_str == "LOSS": losses += 1
            else: scratches += 1
            
            last_trade_time = curr_ts
            
    print("="*50)
    print("TCP 4-POINT HARVEST SIMULATION (Ignoring 30pt Winners)")
    print("="*50)
    print(f"Total Trades: {trades_taken}")
    print(f"Ignored (30+ pts): {ignored}")
    print(f"Wins (4.0 pts) : {wins}")
    print(f"Losses (-12.0) : {losses}")
    print(f"Scratches      : {scratches}")
    if trades_taken > 0:
        print(f"Win Rate       : {(wins/trades_taken)*100:.1f}%")
    print(f"Net PnL        : {total_pnl:+.2f} points (+{total_pnl*10:+.0f} pips)")

if __name__ == "__main__":
    run()
