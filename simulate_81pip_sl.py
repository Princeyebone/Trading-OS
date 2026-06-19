"""
simulate_81pip_sl.py
Tests today's Scalp trades using the Strict H4 filter, but limits the Stop Loss to a maximum of 8.1 points (81 pips),
while keeping the original flexible Take Profit.
"""

import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta

from sqlmodel import Session, create_engine, select
from app.models.trades import Trade

engine = create_engine("postgresql://trading_user:0264442031Qq.@localhost:5432/trading_db")

def get_trend(timeframe, ts_utc):
    rates = mt5.copy_rates_from("XAUUSD", timeframe, ts_utc, 200)
    if rates is None or len(rates) == 0: return "UNKNOWN"
    df = pd.DataFrame(rates)
    df["close"] = df["close"].astype(float)
    df["ema_20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)
    row = df.iloc[-1]
    if pd.isna(row["ema_20"]) or pd.isna(row["ema_50"]): return "UNKNOWN"
    if row["ema_20"] > row["ema_50"]: return "BULLISH"
    elif row["ema_20"] < row["ema_50"]: return "BEARISH"
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

    total_120_pnl = 0.0
    wins_120 = 0
    
    total_81_pnl = 0.0
    wins_81 = 0
    
    taken_trades = 0

    print("\n" + "="*100)
    print(f"{'Trade':<8} | {'Type':<5} | {'120-Pip SL PnL':<15} | {'81-Pip SL PnL':<15} | {'Note':<20}")
    print("="*100)

    for t in trades:
        ts_utc = int(t.opened_at.timestamp())
        h4_trend = get_trend(mt5.TIMEFRAME_H4, ts_utc)
        
        # Apply Strict H4 Filter
        take_trade = False
        if t.direction == "LONG" and h4_trend == "BULLISH": take_trade = True
        elif t.direction == "SHORT" and h4_trend == "BEARISH": take_trade = True
            
        if not take_trade:
            continue
            
        taken_trades += 1

        # Calculate distances
        original_sl_dist = abs(t.planned_entry - t.stop_loss)
        original_tp_dist = abs(t.take_profit_1 - t.planned_entry)
        
        # Bound SL to 8.1 max
        sim_sl_dist = min(original_sl_dist, 8.1)
        sim_tp_dist = original_tp_dist # Flexible TP remains
        
        # Fetch forward M1 rates (2 hours max)
        end_ts = ts_utc + 3600 * 2
        rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, ts_utc, end_ts)
        
        # Calculate Real DB PnL
        old_pnl = (t.take_profit_1 - t.planned_entry) if t.tp1_hit else (t.planned_entry - t.stop_loss)
        if t.status == "LOSS": old_pnl = -abs(t.planned_entry - t.stop_loss)
        elif t.status == "WIN": old_pnl = abs(t.planned_entry - t.take_profit_1)
        else: old_pnl = 0.0
        
        # Simulate 81-pip
        new_pnl = 0.0
        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            for _, row in df.iterrows():
                h, l = row["high"], row["low"]
                if t.direction == "LONG":
                    if l <= t.planned_entry - sim_sl_dist: new_pnl = -sim_sl_dist; break
                    if h >= t.planned_entry + sim_tp_dist: new_pnl = sim_tp_dist; break
                else:
                    if h >= t.planned_entry + sim_sl_dist: new_pnl = -sim_sl_dist; break
                    if l <= t.planned_entry - sim_tp_dist: new_pnl = sim_tp_dist; break

        if new_pnl == 0.0:
            # If it didn't hit 8.1 SL or full TP in 2 hours, assume it trailed out exactly like real life (if real life was < 8.1 loss)
            new_pnl = old_pnl

        total_120_pnl += old_pnl
        if old_pnl > 0: wins_120 += 1
        
        total_81_pnl += new_pnl
        if new_pnl > 0: wins_81 += 1
        
        note = "WIGGLED OUT" if old_pnl > 0 and new_pnl < 0 else ""
        if old_pnl < 0 and new_pnl < 0:
            note = "SAVED 3.9 PTS" if abs(new_pnl) < abs(old_pnl) else ""
            
        print(f"#{t.id:<7} | {t.direction:<5} | {old_pnl:+.2f} pts        | {new_pnl:+.2f} pts        | {note}")

    print("="*100)
    print(f"Filter ON + 120-pip SL Max: Net {total_120_pnl:+.2f} pts | Wins: {wins_120}/{taken_trades}")
    print(f"Filter ON +  81-pip SL Max: Net {total_81_pnl:+.2f} pts | Wins: {wins_81}/{taken_trades}")
    print("="*100)

if __name__ == "__main__":
    run()
