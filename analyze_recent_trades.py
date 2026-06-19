import sys
from sqlmodel import select
from engine.db import get_session
from app.models.signals import Signal
from app.models.trades import Trade

def run():
    session = get_session()
    
    # Query last 10 trades
    statement = (
        select(Trade, Signal)
        .join(Signal)
        .order_by(Trade.opened_at.desc())
        .limit(10)
    )
    
    results = session.exec(statement).all()
    
    if not results:
        print("No trades found in the database.")
        session.close()
        return
        
    print("="*80)
    print("LAST 10 TRADES ANALYSIS")
    print("="*80)
    
    for trade, signal in results: # Chronological (newest first)
        print(f"Trade ID: {trade.id}")
        print(f"Time: {trade.opened_at}")
        # The session tells us which engine took it (SCALP, ASIAN, NY, LONDON)
        # For M1/M5, it is usually "SCALP". For M15, it's the market session.
        engine_str = signal.session
        setup_type = signal.type if hasattr(signal, 'type') else 'UNKNOWN'
        
        # Sometimes scalping setups are saved in skip_reason due to schema limits
        if engine_str == "SCALP" and signal.skip_reason and signal.skip_reason != "None":
            setup_type = signal.skip_reason
            
        print(f"Engine: {engine_str}")
        print(f"Setup/Signal: {setup_type}")
        print(f"Direction: {trade.direction}")
        print(f"Entry: {trade.actual_entry}")
        print(f"Status: {trade.status}")
        
        # Check PnL
        if trade.status == "CLOSED" or trade.status == "WIN" or trade.status == "LOSS" or trade.status == "BE":
            # Just print closed, not trying to compute exact pips without closing price
            print(f"Result: {trade.status}")
        print("-" * 80)
        
    session.close()

if __name__ == "__main__":
    run()
