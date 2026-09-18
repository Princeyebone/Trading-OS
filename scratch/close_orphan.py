import sys
import os
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import broker_executor
from engine.db import get_session
from app.models.trades import Trade
from sqlmodel import select

def main():
    if not broker_executor._init_mt5():
        print("Failed to init MT5")
        return

    ticket = 58121431357
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        print(f"Position {ticket} not found in MT5 or already closed.")
    else:
        p = positions[0]
        print(f"Closing position {ticket}: {p.symbol}, {p.type}, volume: {p.volume}")
        result = broker_executor.close_position(
            ticket=p.ticket,
            symbol=p.symbol
        )
        print("Close result:", result)

    # Update the database to reflect it's closed
    print("Updating Database...")
    with get_session() as session:
        trade = session.exec(select(Trade).where(Trade.broker_order_id == str(ticket))).first()
        if trade:
            trade.status = "CLOSED"
            session.add(trade)
            session.commit()
            print(f"Trade {trade.id} updated to CLOSED in database.")
        else:
            print("Trade not found in database.")

if __name__ == "__main__":
    main()
