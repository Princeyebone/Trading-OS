import sys
import os
import MetaTrader5 as mt5
from sqlmodel import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.db import get_session
from app.models.trades import Trade
from app.models.signals import Signal
from app.models.trades import TradeJournal

def main():
    print("--- MT5 LIVE POSITIONS ---")
    if not mt5.initialize():
        print("MT5 initialize failed")
    else:
        positions = mt5.positions_get()
        if not positions:
            print("No open positions in MT5.")
        else:
            for p in positions:
                print(f"Ticket: {p.ticket} | Symbol: {p.symbol} | Volume: {p.volume} | Profit: ${p.profit:.2f}")
        mt5.shutdown()

    print("\n--- DATABASE OPEN TRADES ---")
    with get_session() as session:
        open_trades = session.exec(select(Trade).where(Trade.status == "OPEN")).all()
        if not open_trades:
            print("No open trades in DB.")
        
        for t in open_trades:
            sig = session.exec(select(Signal).where(Signal.id == t.signal_id)).first()
            journal = session.exec(select(TradeJournal).where(TradeJournal.trade_id == t.id)).first()
            strat = sig.session if sig else "Unknown"
            reasoning = journal.pre_trade_analysis if journal else "No journal entry"
            print(f"DB Trade ID: {t.id} | Broker Ticket: {t.broker_order_id} | Direction: {t.direction} | Strategy: {strat}")
            print(f"  -> Reasoning: {reasoning}")
            print("-" * 40)

if __name__ == "__main__":
    main()
