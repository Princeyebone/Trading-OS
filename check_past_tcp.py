import sys
from datetime import datetime, timezone, timedelta
from sqlmodel import select
from engine.db import get_session
from app.models.signals import Signal
from app.models.trades import Trade
import pandas as pd
import MetaTrader5 as mt5

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    session = get_session()
    
    # Query all TCP trades from the DB
    statement = (
        select(Trade, Signal)
        .join(Signal)
        .where(Signal.session == 'TCP')
    )
    
    results = session.exec(statement).all()
    
    if not results:
        print("No TCP trades found in the database.")
        session.close()
        return
        
    print(f"Found {len(results)} TCP trades in the database.")
    print("="*60)
    
    SL_DIST = 12.0
    HARVEST_DIST = 4.0
    
    wins = 0
    losses = 0
    total_pnl = 0.0
    ignored = 0
    
    for trade, signal in results:
        entry_time = trade.opened_at
        entry_price = trade.actual_entry
        direction = trade.direction
        
        # Simulate forward 24 hours
        end_time = entry_time + timedelta(hours=24)
        rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, entry_time, end_time)
        
        if rates is None or len(rates) == 0:
            print(f"[{entry_time}] {direction} @ {entry_price} | No MT5 data found")
            continue
            
        m1_df = pd.DataFrame(rates)
        mfe_30 = False
        
        # First pass: Check if it went to 30+ points
        for _, row in m1_df.iterrows():
            h, l = row["high"], row["low"]
            if direction == "BULLISH" or direction == "LONG":
                if l <= entry_price - SL_DIST: break # Stopped out before 30pts
                if h >= entry_price + 30.0:
                    mfe_30 = True
                    break
            else:
                if h >= entry_price + SL_DIST: break
                if l <= entry_price - 30.0:
                    mfe_30 = True
                    break
                    
        if mfe_30:
            print(f"[{entry_time}] {direction} @ {entry_price} | IGNORED (Hit 30+ pts)")
            ignored += 1
            continue
            
        # Second pass: Check if we harvested at 4.0 points
        pnl = 0.0
        result_str = "TIMEOUT"
        
        for _, row in m1_df.iterrows():
            h, l = row["high"], row["low"]
            if direction == "BULLISH" or direction == "LONG":
                if l <= entry_price - SL_DIST: 
                    pnl = -SL_DIST
                    result_str = "LOSS"
                    break
                if h >= entry_price + HARVEST_DIST: 
                    pnl = HARVEST_DIST
                    result_str = "WIN (Harvest)"
                    break
            else:
                if h >= entry_price + SL_DIST: 
                    pnl = -SL_DIST
                    result_str = "LOSS"
                    break
                if l <= entry_price - HARVEST_DIST: 
                    pnl = HARVEST_DIST
                    result_str = "WIN (Harvest)"
                    break
                    
        print(f"[{entry_time}] {direction} @ {entry_price} | Result: {result_str} | PnL: {pnl:+.1f}")
        
        total_pnl += pnl
        if "WIN" in result_str: wins += 1
        elif result_str == "LOSS": losses += 1

    print("="*60)
    print("TCP 4-POINT HARVEST SIMULATION (Ignoring 30pt Winners)")
    print("="*60)
    
    trades_taken = wins + losses
    print(f"Total Database Trades Analyzed: {len(results)}")
    print(f"Ignored (30+ pts): {ignored}")
    print(f"Trades Harvested : {trades_taken}")
    print(f"Wins (+4.0 pts)  : {wins}")
    print(f"Losses (-12.0)   : {losses}")
    if trades_taken > 0:
        print(f"Win Rate         : {(wins/trades_taken)*100:.1f}%")
    print(f"Net PnL          : {total_pnl:+.2f} points (+{total_pnl*10:+.0f} pips)")
    
    session.close()

if __name__ == "__main__":
    run()
