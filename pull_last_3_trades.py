import sys
from datetime import datetime, timezone
from sqlmodel import select
from engine.db import get_session
from app.models.signals import Signal
from app.models.trades import Trade

def run():
    session = get_session()
    
    # Query last 3 trades
    statement = (
        select(Trade, Signal)
        .join(Signal)
        .order_by(Trade.opened_at.desc())
        .limit(3)
    )
    
    results = session.exec(statement).all()
    
    print("--- LAST 3 EXECUTED TRADES ---")
    for trade, signal in reversed(results): # reverse to show chronological order
        print(f"[{trade.opened_at}] Timeframe: {signal.timeframe}")
        print(f"   Direction: {trade.direction}")
        print(f"   Entry: {trade.actual_entry}")
        print(f"   SL: {trade.stop_loss}")
        print(f"   Status: {trade.status}")
        print(f"   Signal Type: {signal.verdict} (Assume EMA Pullback if SCALP)")
        print("-" * 50)

    session.close()

if __name__ == "__main__":
    run()
