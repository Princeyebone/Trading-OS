"""
simulate_today_filtered.py
Simulates today's trades using the wide stop loss (original trades),
but applies the H4 Trend Filter (Only BUY when H4 Bullish, Only SELL when H4 Bearish).
"""

import sys, os
from datetime import datetime, timezone
import pandas as pd
import MetaTrader5 as mt5
import ta

# DB Setup
from sqlmodel import Session, create_engine, select
from app.models.trades import Trade

engine = create_engine("postgresql://trading_user:0264442031Qq.@localhost:5432/trading_db")

def get_trend(timeframe, ts_utc):
    rates = mt5.copy_rates_from("XAUUSD", timeframe, ts_utc, 200)
    if rates is None or len(rates) == 0:
        return "UNKNOWN"
        
    df = pd.DataFrame(rates)
    df["close"] = df["close"].astype(float)
    df["ema_20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)
    
    row = df.iloc[-1]
    if pd.isna(row["ema_20"]) or pd.isna(row["ema_50"]):
        return "UNKNOWN"
        
    if row["ema_20"] > row["ema_50"]:
        return "BULLISH"
    elif row["ema_20"] < row["ema_50"]:
        return "BEARISH"
    else:
        return "MIXED"

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with Session(engine) as session:
        statement = select(Trade).where(Trade.opened_at >= start_of_day)
        trades = session.exec(statement).all()

    total_original_pnl = 0.0
    total_original_wins = 0
    
    total_strict_pnl = 0.0
    total_strict_wins = 0
    strict_count = 0
    
    total_eased_pnl = 0.0
    total_eased_wins = 0
    eased_count = 0

    print("\n" + "="*115)
    print(f"{'Trade':<8} | {'Type':<5} | {'H4':<8} | {'H1':<8} | {'Orig PnL':<15} | {'Strict Action':<17} | {'Eased Action':<17}")
    print("="*115)

    for t in trades:
        old_pnl_pts = (t.take_profit_1 - t.planned_entry) if t.tp1_hit else (t.planned_entry - t.stop_loss)
        if t.status == "LOSS": old_pnl_pts = -abs(t.planned_entry - t.stop_loss)
        elif t.status == "WIN": old_pnl_pts = abs(t.planned_entry - t.take_profit_1)
        else: old_pnl_pts = 0.0
            
        total_original_pnl += old_pnl_pts
        if old_pnl_pts > 0: total_original_wins += 1

        ts_utc = int(t.opened_at.timestamp())
        h4_trend = get_trend(mt5.TIMEFRAME_H4, ts_utc)
        h1_trend = get_trend(mt5.TIMEFRAME_H1, ts_utc)
        
        # Strict Filter: H4 must match
        strict_take = False
        if t.direction == "LONG" and h4_trend == "BULLISH": strict_take = True
        elif t.direction == "SHORT" and h4_trend == "BEARISH": strict_take = True
            
        # Eased Filter: H1 must match (more responsive to bounces)
        eased_take = False
        if t.direction == "LONG" and h1_trend == "BULLISH": eased_take = True
        elif t.direction == "SHORT" and h1_trend == "BEARISH": eased_take = True
            
        strict_act = "TAKEN" if strict_take else "BLOCKED"
        eased_act = "TAKEN" if eased_take else "BLOCKED"
        
        if strict_take:
            total_strict_pnl += old_pnl_pts
            if old_pnl_pts > 0: total_strict_wins += 1
            strict_count += 1
            
        if eased_take:
            total_eased_pnl += old_pnl_pts
            if old_pnl_pts > 0: total_eased_wins += 1
            eased_count += 1
            
        old_str = f"{old_pnl_pts:+.2f}"
        print(f"#{t.id:<7} | {t.direction:<5} | {h4_trend:<8} | {h1_trend:<8} | {old_str:<15} | {strict_act:<17} | {eased_act:<17}")

    print("="*115)
    print(f"1. Original (Take All)   : Net {total_original_pnl:+.2f} pts | Wins: {total_original_wins}/{len(trades)}")
    print(f"2. Strict Filter (H4)    : Net {total_strict_pnl:+.2f} pts | Wins: {total_strict_wins}/{strict_count}")
    print(f"3. Eased Filter (H1)     : Net {total_eased_pnl:+.2f} pts | Wins: {total_eased_wins}/{eased_count}")



if __name__ == "__main__":
    run()
