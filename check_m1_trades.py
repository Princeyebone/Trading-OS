import sys
from datetime import datetime, timezone, timedelta
from sqlmodel import select
from engine.db import get_session
from app.models.signals import Signal
from app.models.trades import Trade

def check_trades():
    session = get_session()
    now = datetime.now(timezone.utc)
    # Start of today
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Query all trades created today
    statement = (
        select(Trade, Signal)
        .join(Signal)
        .where(Trade.opened_at >= start_of_today)
    )
    
    results = session.exec(statement).all()
    
    m1_trades = []
    other_trades = []
    
    for trade, signal in results:
        if signal.timeframe == 'M1':
            m1_trades.append((trade, signal))
        else:
            other_trades.append((trade, signal))
            
    print(f"Total Trades Today: {len(results)}")
    print(f"M1 Hyper-Scalps: {len(m1_trades)}")
    print(f"M5 Scalps: {len(other_trades)}")
    
    print("\n--- M1 Hyper-Scalp Details ---")
    if not m1_trades:
        print("No M1 trades taken today.")
    for trade, signal in m1_trades:
        print(f"[{trade.opened_at}] {trade.direction} @ {trade.actual_entry} | Status: {trade.status}")
        
    print("\n--- M5 Scalp Details ---")
    if not other_trades:
        print("No M5 trades taken today.")
    for trade, signal in other_trades:
        print(f"[{trade.opened_at}] {trade.direction} @ {trade.actual_entry} | Status: {trade.status}")

    session.close()

if __name__ == "__main__":
    check_trades()
