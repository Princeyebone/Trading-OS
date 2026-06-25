import sys
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.pattern_detector import detect_order_blocks

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=30)
    
    print("Fetching M1 and M15 data...")
    m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, start_time, now)
    h1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start_time, now)
    
    m1_df = pd.DataFrame(m1_rates)
    m1_df['time'] = pd.to_datetime(m1_df['time'], unit='s', utc=True)
    m1_df.set_index('time', inplace=True)
    
    h1_df = pd.DataFrame(h1_rates)
    h1_df['time'] = pd.to_datetime(h1_df['time'], unit='s', utc=True)
    h1_df.set_index('time', inplace=True)
    h1_df['ema50'] = ta.trend.ema_indicator(h1_df['close'], window=50)
    
    # Resample M1 to M15 to match real-time construction
    m15_df = m1_df.resample('15min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last', 'real_volume':'sum'})
    m15_df.dropna(inplace=True)

    pure_trail_pnl = 0.0
    harvest_trail_pnl = 0.0
    
    trade_count = 0
    
    # Simple scan logic mimicking momentum_runner
    for i in range(50, len(m15_df) - 10):
        window_end_time = m15_df.index[i]
        
        # Get H1 trend at this time
        past_h1 = h1_df[h1_df.index <= window_end_time]
        if past_h1.empty or pd.isna(past_h1['ema50'].iloc[-1]): continue
        
        h1_close = past_h1['close'].iloc[-1]
        h1_ema = past_h1['ema50'].iloc[-1]
        is_bullish = h1_close > h1_ema
        trend_dir = "BULLISH" if is_bullish else "BEARISH"
        
        # Look for OB in the last 40 M15 candles
        m15_window = m15_df.iloc[i-40:i+1].reset_index(drop=True)
        obs = detect_order_blocks(m15_window, direction=trend_dir.lower())
        valid_obs = [ob for ob in obs if ob['direction'] == trend_dir]
        
        if not valid_obs: continue
        
        # Just use the latest valid OB
        ob = valid_obs[-1]
        entry_price = ob['high'] if is_bullish else ob['low']
        
        # Fast forward M1 data to simulate execution and management
        future_m1 = m1_df[m1_df.index > window_end_time]
        
        # Wait for Limit Order Trigger
        triggered = False
        trigger_time = None
        for t, row in future_m1.iterrows():
            if t > window_end_time + timedelta(hours=8): break # Expire after 8 hours
            
            if is_bullish and row['low'] <= entry_price:
                triggered = True; trigger_time = t; break
            if not is_bullish and row['high'] >= entry_price:
                triggered = True; trigger_time = t; break
                
        if not triggered: continue
        
        # We are in a trade
        trade_count += 1
        
        # Management tracking
        highest_profit_pips = 0.0
        
        # Logic A (Pure Trail 30 pips)
        a_locked = 0.0
        a_closed = False
        a_pnl = 0.0
        
        # Logic B (Harvest 50% at 150 pips, trail 30 pips)
        b_locked = 0.0
        b_closed_half = False
        b_closed_full = False
        b_pnl = 0.0
        
        trade_m1 = future_m1[future_m1.index >= trigger_time]
        
        for t, row in trade_m1.iterrows():
            if is_bullish:
                profit_pips = (row['high'] - entry_price) * 10.0
                pullback_pips = (entry_price - row['low']) * 10.0
                # Using close for simplicity in trailing checks to avoid intra-candle phantom hits
                current_profit = (row['close'] - entry_price) * 10.0 
            else:
                profit_pips = (entry_price - row['low']) * 10.0
                pullback_pips = (row['high'] - entry_price) * 10.0
                current_profit = (entry_price - row['close']) * 10.0
                
            if current_profit > highest_profit_pips:
                highest_profit_pips = current_profit
                
            # Both logics use 30-pip SL initially
            if highest_profit_pips < 30.0 and pullback_pips >= 30.0:
                # Stop loss hit
                if not a_closed: a_pnl = -30.0; a_closed = True
                if not b_closed_full: 
                    b_pnl += -30.0 if not b_closed_half else -15.0 # half volume remains
                    b_closed_full = True
                break
                
            # Update locks
            trail_level = highest_profit_pips - 30.0
            if trail_level > a_locked: a_locked = trail_level
            if trail_level > b_locked: b_locked = trail_level
            
            # Check Logic A Trail Hit
            if not a_closed and current_profit <= a_locked:
                a_pnl = a_locked
                a_closed = True
                
            # Check Logic B Harvest
            if not b_closed_half and highest_profit_pips >= 150.0:
                b_pnl += 75.0 # 50% of 150 pips
                b_closed_half = True
                
            # Check Logic B Trail Hit
            if not b_closed_full and current_profit <= b_locked:
                if b_closed_half:
                    b_pnl += (b_locked * 0.5)
                else:
                    b_pnl += b_locked
                b_closed_full = True
                
            if a_closed and b_closed_full:
                break
                
        # If open at end of data, close at market
        if not a_closed: a_pnl = current_profit
        if not b_closed_full:
            b_pnl += (current_profit * 0.5) if b_closed_half else current_profit
            
        pure_trail_pnl += a_pnl
        harvest_trail_pnl += b_pnl

    print("="*60)
    print("M15 Runner Exit Logic Simulation (30 Days)")
    print(f"Total Setups Triggered: {trade_count}")
    print(f"Logic A (Pure 30-pip Trail): {pure_trail_pnl:.1f} pips")
    print(f"Logic B (50% Harvest @ 150 pips + 30-pip Trail): {harvest_trail_pnl:.1f} pips")
    print("="*60)

if __name__ == "__main__":
    run()
