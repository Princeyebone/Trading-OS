"""
simulate_crown.py
Tests the existing Crown/Base Momentum Scalp modules over 30 days.
"""

import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

from engine.scalping_engine import ScalpingEngine

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
    
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_date, now)
    m15_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M15, start_date, now)
    
    m5_df = pd.DataFrame(m5_rates)
    m15_df = pd.DataFrame(m15_rates)
    
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    m15_df['time'] = pd.to_datetime(m15_df['time'], unit='s', utc=True)
    
    engine = ScalpingEngine(m5_df, m15_df)
    
    SL_DIST = 12.0
    TP_DIST = 20.0
    
    total_pnl = 0.0
    wins, losses, scratches = 0, 0, 0
    trades_taken = 0

    print(f"Running Crown/Base Momentum Backtest: 30 Days")
    print("="*100)

    for i in range(50, len(m5_df)-1):
        # Only extract base/crown
        sigs = engine.scan(i)
        base_crown_sigs = [s for s in sigs if s['type'] in ('BASE_MOMENTUM', 'CROWN_MOMENTUM')]
        
        for sig in base_crown_sigs:
            trades_taken += 1
            direction = sig['direction']
            curr_ts = m5_df['time'].iloc[i]
            entry_price = sig['price']
            
            # Simulate forward
            end_ts = curr_ts + timedelta(hours=4)
            m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, curr_ts, end_ts)
            
            pnl = 0.0
            result_str = "TIMEOUT"
            
            if m1_rates is not None and len(m1_rates) > 0:
                m1_df = pd.DataFrame(m1_rates)
                for _, row in m1_df.iterrows():
                    h, l = row["high"], row["low"]
                    if direction == "BULLISH":
                        if l <= entry_price - SL_DIST: pnl = -SL_DIST; result_str = "LOSS"; break
                        if h >= entry_price + TP_DIST: pnl = TP_DIST; result_str = "WIN"; break
                    else:
                        if h >= entry_price + SL_DIST: pnl = -SL_DIST; result_str = "LOSS"; break
                        if l <= entry_price - TP_DIST: pnl = TP_DIST; result_str = "WIN"; break
                        
            total_pnl += pnl
            if result_str == "WIN": wins += 1
            elif result_str == "LOSS": losses += 1
            else: scratches += 1

    print("="*100)
    print(f"CROWN/BASE MOMENTUM RESULTS (30 Days)")
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
