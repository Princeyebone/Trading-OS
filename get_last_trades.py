import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import select, Session
from engine.db import get_session
from app.models.trades import Trade, TradeJournal, TradeOutcome
from app.models.signals import Signal

def fetch_last_two_tcp_trades():
    session = get_session()
    
    # We want the last 2 trades where the session/strategy was TCP (i.e. not SCALP)
    statement = select(Trade, Signal, TradeJournal, TradeOutcome)\
        .join(Signal, Trade.signal_id == Signal.id)\
        .outerjoin(TradeJournal, Trade.id == TradeJournal.trade_id)\
        .outerjoin(TradeOutcome, Trade.id == TradeOutcome.trade_id)\
        .where(Signal.session != "SCALP")\
        .order_by(Trade.opened_at.desc())\
        .limit(2)
        
    results = session.exec(statement).all()
    
    if not results:
        print("No TCP trades found.")
        return
        
    for trade, signal, journal, outcome in results:
        print("="*80)
        print(f"Trade ID: {trade.id} | Status: {trade.status} | Direction: {trade.direction}")
        print(f"Opened At: {trade.opened_at} | Closed At: {trade.closed_at}")
        print(f"Entry: {trade.actual_entry} (Planned: {trade.planned_entry}) | SL: {trade.stop_loss} | TP1: {trade.take_profit_1}")
        
        if outcome:
            print(f"Outcome Reason: {outcome.exit_reason} | PnL Pips: {outcome.pnl_pips} | PnL $: {outcome.pnl_dollars}")
            print(f"R Achieved: {outcome.r_achieved} | MFE: {outcome.max_favorable_excursion} | MAE: {outcome.max_adverse_excursion}")
        else:
            print("Outcome: None recorded.")
            
        print(f"\nSignal Info:")
        print(f"Timeframe: {signal.timeframe} | Session: {signal.session}")
        print(f"Verdict: {signal.verdict} | Confidence: {signal.confidence}")
        
        print(f"\nJournal (AI Pre-Trade Analysis):")
        if journal and journal.pre_trade_analysis:
            print(f"{journal.pre_trade_analysis}")
        else:
            print("No journal entry.")
            
        print(f"\nJournal (AI Post-Trade Analysis):")
        if journal and journal.post_trade_analysis:
            print(f"{journal.post_trade_analysis}")
            print(f"What Went Wrong: {journal.what_went_wrong}")
        else:
            print("No post-trade analysis.")
        print("="*80)
        print()

if __name__ == "__main__":
    fetch_last_two_tcp_trades()
