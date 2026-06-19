import sys
from sqlmodel import select
from engine.db import get_session
from app.models.signals import Signal
from app.models.trades import Trade

def run():
    session = get_session()
    
    # Query last 5 losses
    statement = (
        select(Trade, Signal)
        .join(Signal)
        .where(Trade.status == 'LOSS')
        .order_by(Trade.opened_at.desc())
        .limit(5)
    )
    
    results = session.exec(statement).all()
    
    if not results:
        print("No losses found in the database.")
        session.close()
        return
        
    print("="*80)
    print("LAST 5 LOSSES DEEP ANALYSIS")
    print("="*80)
    
    for trade, signal in results: # Chronological (newest first)
        print(f"Time: {trade.opened_at}")
        print(f"Strategy/Type: {signal.session} / {signal.type if hasattr(signal, 'type') else 'UNKNOWN'}")
        print(f"Direction: {trade.direction}")
        print(f"Entry: {trade.actual_entry}")
        if hasattr(signal, 'reason'): print(f"Reason: {signal.reason}")
        print("-" * 80)
        
    session.close()

if __name__ == "__main__":
    run()
