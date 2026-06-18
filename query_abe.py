from datetime import timedelta
from sqlmodel import Session, select
from app.database import engine
from app.models.signals import Signal
from app.models.trades import Trade, TradeJournal

with Session(engine) as session:
    # Get the last 30 WAIT signals
    wait_signals = session.exec(
        select(Signal)
        .where(Signal.verdict == 'WAIT')
        .order_by(Signal.created_at.desc())
        .limit(30)
    ).all()
    
    if not wait_signals:
        print("No WAIT signals found.")
        import sys
        sys.exit(0)
        
    wait_signals.reverse() # Oldest of the 30 first

    count_became_abe = 0

    for wait_signal in wait_signals:
        time_start = wait_signal.created_at + timedelta(hours=1)
        time_end = wait_signal.created_at + timedelta(hours=3)
        
        # Look for TRADE signals within 1 to 3 hours after this wait_signal
        future_trades = session.exec(
            select(Signal)
            .where(Signal.verdict == 'TRADE')
            .where(Signal.created_at >= time_start)
            .where(Signal.created_at <= time_end)
        ).all()
        
        found_abe = False
        for f_trade in future_trades:
            # Check TradeJournal for this signal to see if it's ABE
            trade_obj = session.exec(select(Trade).where(Trade.signal_id == f_trade.id)).first()
            if trade_obj:
                journal = session.exec(select(TradeJournal).where(TradeJournal.trade_id == trade_obj.id)).first()
                if journal and journal.pre_trade_analysis and "[Strategy: ABE]" in journal.pre_trade_analysis:
                    found_abe = True
                    break
        
        if found_abe:
            count_became_abe += 1

    print(f"Total WAIT cycles checked: {len(wait_signals)}")
    print(f"Number of those that saw a valid ABE trade 1-3 hours later: {count_became_abe}")
