import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
from engine.scalping_engine import ScalpingEngine

def simulate_outcome(m1_df: pd.DataFrame, entry_idx: int, direction: str, entry_price: float) -> str:
    # 12.0 pt SL, 1.0 pt harvest step trailing
    SL_DIST = 12.0
    # Simulate forward 24 hours
    for i in range(len(m1_df)):
        h, l = m1_df["high"].iloc[i], m1_df["low"].iloc[i]
        
        if direction == "BULLISH":
            if l <= entry_price - SL_DIST: return "LOSS"
            if h >= entry_price + 1.0: return "WIN" # Scalp tight harvest
        else:
            if h >= entry_price + SL_DIST: return "LOSS"
            if l <= entry_price - 1.0: return "WIN"
            
    return "SCRATCH"

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=14)
    
    # Fetch 14 days of M5 and M15 data
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_date - timedelta(days=5), now)
    m15_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M15, start_date - timedelta(days=5), now)
    
    m5_df = pd.DataFrame(m5_rates)
    m15_df = pd.DataFrame(m15_rates)
    
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    m15_df['time'] = pd.to_datetime(m15_df['time'], unit='s', utc=True)
    
    engine = ScalpingEngine(m5_df, m15_df)
    
    # We will simulate all setups
    # To do this, we override the scan method to return the setup type
    
    stats = {
        "EMA_PULLBACK": {"taken": 0, "wins": 0, "losses": 0},
        "BASE_MOMENTUM": {"taken": 0, "wins": 0, "losses": 0},
        "CROWN_MOMENTUM": {"taken": 0, "wins": 0, "losses": 0},
        "BREAKOUT": {"taken": 0, "wins": 0, "losses": 0},
        "FIBONACCI": {"taken": 0, "wins": 0, "losses": 0},
        "RANGE_BOUNCE": {"taken": 0, "wins": 0, "losses": 0},
        "RANGE_BREAKOUT": {"taken": 0, "wins": 0, "losses": 0},
    }
    
    start_idx = m5_df[m5_df['time'] >= start_date].index.min()
    
    print("Running 14-Day Scalping Module Analysis...")
    
    for i in range(start_idx, len(m5_df)-1):
        curr_ts = m5_df['time'].iloc[i]
        
        # Scan normally
        signals = engine.scan(i, h4_trend="UNKNOWN") # ignore H4 trend to see raw setup performance
        
        if not signals:
            continue
            
        # Get M1 data for simulation
        end_ts = curr_ts + timedelta(hours=24)
        m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, curr_ts, end_ts)
        if m1_rates is None or len(m1_rates) == 0: continue
        m1_df = pd.DataFrame(m1_rates)
        
        for sig in signals:
            stype = sig['type']
            direction = sig['direction']
            price = sig['price']
            
            if stype not in stats:
                continue
                
            outcome = simulate_outcome(m1_df, 0, direction, price)
            
            stats[stype]["taken"] += 1
            if outcome == "WIN":
                stats[stype]["wins"] += 1
            elif outcome == "LOSS":
                stats[stype]["losses"] += 1

    print("\n" + "="*70)
    print(f"{'SETUP MODULE':<20} | {'TAKEN':<6} | {'WINS':<6} | {'LOSS':<6} | {'WIN RATE':<10}")
    print("="*70)
    
    for setup, data in sorted(stats.items(), key=lambda x: x[1]["taken"], reverse=True):
        taken = data["taken"]
        wins = data["wins"]
        losses = data["losses"]
        resolved = wins + losses
        win_rate = (wins / resolved * 100) if resolved > 0 else 0.0
        
        print(f"{setup:<20} | {taken:<6} | {wins:<6} | {losses:<6} | {win_rate:.1f}%")
        
    print("="*70)
    
if __name__ == "__main__":
    run()
