import sys
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=30)
    
    print("Fetching M1 and M5 data...")
    m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, start_time, now)
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_time, now)
    
    m1_df = pd.DataFrame(m1_rates)
    m1_df['time'] = pd.to_datetime(m1_df['time'], unit='s', utc=True)
    m1_df.set_index('time', inplace=True)
    
    m5_df = pd.DataFrame(m5_rates)
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    m5_df.set_index('time', inplace=True)

    # We will test two entry logic variations for a 2-candle impulse:
    # 1. Enter at 50% retracement of the impulse candle
    # 2. Enter at the Open of the impulse candle
    
    def simulate_entry(entry_type, trailing_pips=20.0):
        total_pnl = 0.0
        trade_count = 0
        wins = 0
        losses = 0
        
        for i in range(1, len(m5_df) - 1):
            c1 = m5_df.iloc[i-1]
            c2 = m5_df.iloc[i]
            window_end_time = m5_df.index[i]
            
            is_c1_bearish = c1['close'] < c1['open']
            is_c2_bullish = c2['close'] > c2['open']
            
            is_c1_bullish = c1['close'] > c1['open']
            is_c2_bearish = c2['close'] < c2['open']
            
            c2_range = c2['high'] - c2['low']
            
            direction = None
            entry_price = 0.0
            sl_price = 0.0
            
            # BULLISH 2-CANDLE ENGULFING / SHIFT
            if is_c1_bearish and is_c2_bullish and c2['close'] > c1['high'] and c2_range >= 1.5:
                direction = "LONG"
                if entry_type == "50_PCT":
                    entry_price = c2['low'] + (c2_range * 0.5)
                elif entry_type == "OPEN":
                    entry_price = c2['open']
                sl_price = c2['low'] - 0.5 # 5 pip buffer
                
            # BEARISH 2-CANDLE ENGULFING / SHIFT
            elif is_c1_bullish and is_c2_bearish and c2['close'] < c1['low'] and c2_range >= 1.5:
                direction = "SHORT"
                if entry_type == "50_PCT":
                    entry_price = c2['high'] - (c2_range * 0.5)
                elif entry_type == "OPEN":
                    entry_price = c2['open']
                sl_price = c2['high'] + 0.5 # 5 pip buffer
                
            if not direction:
                continue
                
            # Fast forward M1 data to simulate limit order execution
            future_m1 = m1_df[m1_df.index > window_end_time]
            triggered = False
            trigger_time = None
            
            for t, row in future_m1.iterrows():
                if t > window_end_time + timedelta(hours=4): break # Expire pending limit after 4 hours
                
                if direction == "LONG" and row['low'] <= entry_price:
                    triggered = True; trigger_time = t; break
                if direction == "SHORT" and row['high'] >= entry_price:
                    triggered = True; trigger_time = t; break
                    
            if not triggered: continue
            
            trade_count += 1
            highest_profit_pips = 0.0
            locked_pips = 0.0
            trade_pnl = 0.0
            
            trade_m1 = future_m1[future_m1.index >= trigger_time]
            
            for t, row in trade_m1.iterrows():
                if direction == "LONG":
                    if row['low'] <= sl_price:
                        trade_pnl = (sl_price - entry_price) * 10.0
                        break
                    current_profit = (row['close'] - entry_price) * 10.0
                else:
                    if row['high'] >= sl_price:
                        trade_pnl = (entry_price - sl_price) * 10.0
                        break
                    current_profit = (entry_price - row['close']) * 10.0
                    
                if current_profit > highest_profit_pips:
                    highest_profit_pips = current_profit
                    
                # Trailing logic
                if highest_profit_pips >= trailing_pips:
                    trail = highest_profit_pips - trailing_pips
                    if trail > locked_pips:
                        locked_pips = trail
                        
                # Check trail hit
                if locked_pips > 0 and current_profit <= locked_pips:
                    trade_pnl = locked_pips
                    break
                    
                if t > trigger_time + timedelta(hours=8): # Forced 8 hour close
                    trade_pnl = current_profit
                    break
                    
            if trade_pnl > 0: wins += 1
            else: losses += 1
            total_pnl += trade_pnl
            
        print(f"Setup: Entry at {entry_type} | Trail: {trailing_pips} pips")
        print(f"Total Trades: {trade_count} | Wins: {wins} | Losses: {losses} | Win Rate: {wins/(max(1, wins+losses))*100:.1f}%")
        print(f"Net PnL: {total_pnl:.1f} pips\n")

    print("="*60)
    print("M5 TWO-CANDLE MOMENTUM PULLBACK SIMULATION (30 Days)")
    simulate_entry("50_PCT", trailing_pips=20.0)
    simulate_entry("OPEN", trailing_pips=20.0)
    simulate_entry("50_PCT", trailing_pips=30.0)
    simulate_entry("OPEN", trailing_pips=30.0)
    print("="*60)

if __name__ == "__main__":
    run()
