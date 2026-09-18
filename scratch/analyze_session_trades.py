import sys
import os
from datetime import datetime, timezone
import pandas as pd
from sqlmodel import select

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine.db import get_session
from app.models.trades import Trade
from app.models.signals import Signal

def main():
    session = get_session()
    
    # Target start time: 03:30 UTC (04:30 UK Time, 06:30 MT5 Time)
    start_time = datetime(2026, 7, 6, 3, 30, tzinfo=timezone.utc)
    
    statement = select(Trade).where(Trade.opened_at >= start_time).order_by(Trade.opened_at)
    trades = session.exec(statement).all()
    
    data = []
    for t in trades:
        sys_name = t.system
        if not sys_name and t.signal_id:
            sig = session.get(Signal, t.signal_id)
            if sig:
                sys_name = sig.session
                
        if not sys_name:
            sys_name = "Unknown"
            
        # PnL logic
        pnl_pips = 0.0
        if t.status in ["WIN", "LOSS"] and t.closed_at:
            if t.direction == "LONG" and t.actual_entry and t.take_profit_1: # Hack to get close price if available? No, we don't store close price directly, we might have outcome though.
                pass
                
        # Better: use MT5 history if we want exact pips, but we can just use outcome if it's there
        # Let's get outcomes
        from app.models.trades import TradeOutcome
        outcome = session.exec(select(TradeOutcome).where(TradeOutcome.trade_id == t.id)).first()
        
        pnl_pips = outcome.pnl_pips if outcome else 0.0
        pnl_dollars = outcome.pnl_dollars if outcome else 0.0
        
        # If open, use locked profit as a proxy or just show Open
        state = t.status
        if state == "OPEN":
            pnl_pips = t.locked_profit_pips or 0.0
        
        data.append({
            "ID": t.id,
            "Ticket": t.broker_order_id,
            "System": sys_name,
            "Dir": t.direction,
            "Status": t.status,
            "PnL_Pips": pnl_pips,
            "PnL_$": round(pnl_dollars, 2),
            "Opened": t.opened_at.strftime("%H:%M:%S") if t.opened_at else "N/A"
        })
        
    df = pd.DataFrame(data)
    print("=== TRADES SINCE 04:30 AM (UK TIME) ===")
    if len(df) == 0:
        print("No trades found.")
    else:
        print(df.to_string(index=False))
        
        print("\n=== PERFORMANCE BY SYSTEM ===")
        # Group by system
        for sys_val in df['System'].unique():
            sys_df = df[df['System'] == sys_val]
            wins = len(sys_df[sys_df['Status'] == 'WIN'])
            losses = len(sys_df[sys_df['Status'] == 'LOSS'])
            open_t = len(sys_df[sys_df['Status'] == 'OPEN'])
            total_pips = sys_df['PnL_Pips'].sum()
            total_dollars = sys_df['PnL_$'].sum()
            print(f"System: {sys_val}")
            print(f"  Trades: {len(sys_df)} (W: {wins}, L: {losses}, O: {open_t})")
            print(f"  Net Pips: {total_pips:.1f}")
            print(f"  Net $: ${total_dollars:.2f}\n")

if __name__ == "__main__":
    main()
