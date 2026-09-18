"""
backend/scratch/analyze_mt5_history.py
Fetches recent trades directly from the connected MT5 account, filters for the biggest losses, 
and prints out detailed information to help diagnose the issue.
"""
import sys
import os
import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import broker_executor

def run_analysis():
    print("Initializing MT5...")
    if not broker_executor._init_mt5():
        print("Failed to initialize MT5.")
        return
        
    print("MT5 Connected.")
    account_info = mt5.account_info()
    if account_info:
        print(f"Account: {account_info.login}, Server: {account_info.server}")
        
    # Fetch the last 30 days of history
    date_from = datetime.now() - timedelta(days=30)
    date_to = datetime.now() + timedelta(days=1)
    
    deals = mt5.history_deals_get(date_from, date_to)
    if not deals:
        print("No history deals found in MT5 for the given period.")
        return
        
    print(f"Found {len(deals)} total deals in MT5 history.")
    
    # We want to look at closed trades. 
    # In MT5, a complete trade consists of a deal IN and a deal OUT.
    # We'll filter for deals that realized a profit/loss (deal OUT).
    trades = []
    for d in deals:
        if d.entry == mt5.DEAL_ENTRY_OUT or d.entry == mt5.DEAL_ENTRY_INOUT:
            trades.append({
                "ticket": d.ticket,
                "position_id": d.position_id,
                "symbol": d.symbol,
                "volume": d.volume,
                "price": d.price,
                "profit": d.profit,
                "commission": d.commission,
                "swap": d.swap,
                "magic": d.magic,
                "time": datetime.fromtimestamp(d.time).strftime('%Y-%m-%d %H:%M:%S'),
                "reason": d.reason
            })
            
    df = pd.DataFrame(trades)
    if df.empty:
        print("No closed trades found.")
        return
        
    # Calculate total PnL
    df['total_pnl'] = df['profit'] + df['commission'] + df['swap']
    
    print("\n--- PERFORMANCE SUMMARY ---")
    print(f"Total Trades Analyzed: {len(df)}")
    print(f"Total Gross Profit: ${df['total_pnl'].sum():.2f}")
    
    # Let's find the biggest losses
    print("\n--- BIGGEST LOSSES ---")
    losses = df[df['total_pnl'] < 0].sort_values(by='total_pnl')
    if losses.empty:
        print("No losing trades found!")
    else:
        print(losses[['time', 'symbol', 'volume', 'magic', 'price', 'profit', 'total_pnl']].head(10).to_string())
        
    print("\n--- LOSSES BY MAGIC NUMBER (STRATEGY) ---")
    grouped = losses.groupby('magic').agg(
        loss_count=('ticket', 'count'),
        total_loss_usd=('total_pnl', 'sum'),
        avg_loss=('total_pnl', 'mean')
    ).sort_values(by='total_loss_usd')
    print(grouped.to_string())

if __name__ == "__main__":
    run_analysis()
    mt5.shutdown()
