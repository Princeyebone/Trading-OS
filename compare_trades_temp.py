import sys
import os
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome
from sqlmodel import select

def check_trades():
    session = get_session()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    trades = session.exec(
        select(Trade, TradeOutcome)
        .outerjoin(TradeOutcome, Trade.id == TradeOutcome.trade_id)
        .where(Trade.opened_at >= today_start)
    ).all()
    
    if not mt5.initialize():
        print("MT5 init failed")
        return
        
    db_total_loss = 0.0
    db_total_profit = 0.0
    
    mt5_total_loss = 0.0
    mt5_total_profit = 0.0
    
    print(f"Checking {len(trades)} trades for today:")
    
    for trade, outcome in trades:
        print(f"\n--- Trade #{trade.id} ---")
        print(f"Status: {trade.status}, Broker ID: {trade.broker_order_id}")
        
        # DB Metrics
        db_pnl = outcome.pnl_dollars if outcome else 0.0
        db_pnl_pips = outcome.pnl_pips if outcome else 0.0
        if db_pnl > 0:
            db_total_profit += db_pnl
        else:
            db_total_loss += db_pnl
            
        print(f"DB PnL: ${db_pnl:.2f} ({db_pnl_pips} pips)")
        
        # MT5 Metrics
        if not trade.broker_order_id:
            print("No Broker Order ID in DB!")
            continue
            
        deals = mt5.history_deals_get(position=int(trade.broker_order_id))
        mt5_pnl = 0.0
        if deals:
            for d in deals:
                if d.entry == 1: # DEAL_ENTRY_OUT
                    mt5_pnl += d.profit
            print(f"MT5 PnL: ${mt5_pnl:.2f}")
        else:
            # Check if it's still open
            pos = mt5.positions_get(ticket=int(trade.broker_order_id))
            if pos:
                print(f"MT5 Status: OPEN (Live Profit: ${pos[0].profit:.2f})")
            else:
                print("MT5 Status: NOT FOUND IN HISTORY OR OPEN!")
                
        if mt5_pnl > 0:
            mt5_total_profit += mt5_pnl
        elif mt5_pnl < 0:
            mt5_total_loss += mt5_pnl
            
        if abs(db_pnl - mt5_pnl) > 0.01 and mt5_pnl != 0.0:
            print(f"DISCREPANCY DETECTED! DB: ${db_pnl:.2f} vs MT5: ${mt5_pnl:.2f}")
            
    print("\n==================================")
    print("SUMMARY")
    print("==================================")
    print(f"DB Total Profit: ${db_total_profit:.2f}")
    print(f"DB Total Loss: ${db_total_loss:.2f}")
    print(f"DB Net: ${(db_total_profit + db_total_loss):.2f}")
    print("----------------------------------")
    print(f"MT5 Total Profit: ${mt5_total_profit:.2f}")
    print(f"MT5 Total Loss: ${mt5_total_loss:.2f}")
    print(f"MT5 Net: ${(mt5_total_profit + mt5_total_loss):.2f}")

if __name__ == "__main__":
    check_trades()
