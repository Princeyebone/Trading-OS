"""
simulate_today.py
Simulates today's SCALP trades with the new 6.0 pt max stop loss.
"""

import sys, os
from datetime import datetime, timezone
import pandas as pd
import MetaTrader5 as mt5

from sqlmodel import Session, create_engine, select
from app.models.trades import Trade

engine = create_engine("postgresql://trading_user:0264442031Qq.@localhost:5432/trading_db")

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with Session(engine) as session:
        statement = select(Trade).where(Trade.opened_at >= start_of_day)
        trades = session.exec(statement).all()

    print(f"Found {len(trades)} SCALP trades taken today.")
    
    old_net_pts = 0.0
    new_net_pts = 0.0
    old_wins = 0
    new_wins = 0

    print("\n" + "="*80)
    print(f"{'Trade':<8} | {'Type':<5} | {'Entry':<8} | {'Old PnL (pts)':<15} | {'New PnL (pts)':<15}")
    print("="*80)

    for t in trades:
        # Fetch M1 bars from entry time to +1 hour to simulate the path
        # Use UTC timestamp
        start_ts = int(t.opened_at.timestamp())
        end_ts = start_ts + 3600 * 2  # 2 hours max
        
        rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, start_ts, end_ts)
        if rates is None or len(rates) == 0:
            continue
            
        df = pd.DataFrame(rates)
        
        # Original PnL approximation
        old_pnl_pts = (t.take_profit_1 - t.planned_entry) if t.tp1_hit else (t.planned_entry - t.stop_loss) # Just an approximation for display
        if t.status == "LOSS":
            old_pnl_pts = -abs(t.planned_entry - t.stop_loss)
        elif t.status == "WIN":
            old_pnl_pts = abs(t.planned_entry - t.take_profit_1)
        else:
            old_pnl_pts = 0.0
        
        # New Simulation
        # TP was likely +5 or what was recorded. Let's use 5.0 for baseline or the actual TP
        tp_dist = 5.0
        sl_dist = 6.0
        
        tp_price = t.planned_entry + tp_dist if t.direction == "LONG" else t.planned_entry - tp_dist
        sl_price = t.planned_entry - sl_dist if t.direction == "LONG" else t.planned_entry + sl_dist
        
        new_pnl_pts = None
        for _, row in df.iterrows():
            h, l = row["high"], row["low"]
            
            if t.direction == "LONG":
                if l <= sl_price:
                    new_pnl_pts = -sl_dist
                    break
                if h >= tp_price:
                    new_pnl_pts = tp_dist
                    break
            else:
                if h >= sl_price:
                    new_pnl_pts = -sl_dist
                    break
                if l <= tp_price:
                    new_pnl_pts = tp_dist
                    break
                    
        if new_pnl_pts is None:
            new_pnl_pts = 0.0 # Didn't hit either within 2 hours
            
        # Add to totals
        old_net_pts += old_pnl_pts
        new_net_pts += new_pnl_pts
        
        if old_pnl_pts > 0: old_wins += 1
        if new_pnl_pts > 0: new_wins += 1
        
        # Color coding for terminal output
        old_str = f"{old_pnl_pts:+.2f}"
        new_str = f"{new_pnl_pts:+.2f}"
        
        print(f"#{t.id:<7} | {t.direction:<5} | {t.planned_entry:<8.2f} | {old_str:<15} | {new_str:<15}")

    print("="*80)
    print(f"Old System: Net {old_net_pts:+.2f} pts | Wins: {old_wins}/{len(trades)}")
    print(f"New System: Net {new_net_pts:+.2f} pts | Wins: {new_wins}/{len(trades)}")
    
if __name__ == "__main__":
    run()
