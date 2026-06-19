"""
simulate_early_exit.py
Tests the 'Active Defense Early Exit' mechanism on today's filtered Scalp trades.
Method A: Standard 12.0 pt (120-pip) SL + DB TP.
Method B: Standard 12.0 pt SL + DB TP + Early Exit if M15 candle closes across the 20 EMA.
"""

import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta

from sqlmodel import Session, create_engine, select
from app.models.trades import Trade

engine = create_engine("postgresql://trading_user:0264442031Qq.@localhost:5432/trading_db")

def get_h4_trend(ts_utc):
    rates = mt5.copy_rates_from("XAUUSD", mt5.TIMEFRAME_H4, ts_utc, 200)
    if rates is None or len(rates) == 0: return "UNKNOWN"
    df = pd.DataFrame(rates)
    df["close"] = df["close"].astype(float)
    df["ema_20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)
    row = df.iloc[-1]
    if pd.isna(row["ema_20"]): return "UNKNOWN"
    if row["ema_20"] > row["ema_50"]: return "BULLISH"
    elif row["ema_20"] < row["ema_50"]: return "BEARISH"
    return "MIXED"

def get_m15_data(start_ts, end_ts):
    rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M15, start_ts - 86400*2, end_ts + 3600*4)
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df["close"] = df["close"].astype(float)
    df["ema_20"] = ta.trend.ema_indicator(df["close"], window=20)
    return df

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with Session(engine) as session:
        statement = select(Trade).where(Trade.opened_at >= start_of_day)
        trades = session.exec(statement).all()

    total_a_pnl = 0.0
    wins_a = 0
    total_b_pnl = 0.0
    wins_b = 0
    
    taken_trades = 0

    print("\n" + "="*110)
    print(f"{'Trade':<8} | {'Type':<5} | {'Method A (120-pip SL)':<25} | {'Method B (Early Exit)':<25} | {'Note':<20}")
    print("="*110)

    for t in trades:
        ts_utc = int(t.opened_at.timestamp())
        h4_trend = get_h4_trend(ts_utc)
        
        # Strict H4 Filter
        take_trade = False
        if t.direction == "LONG" and h4_trend == "BULLISH": take_trade = True
        elif t.direction == "SHORT" and h4_trend == "BEARISH": take_trade = True
            
        if not take_trade: continue
        taken_trades += 1

        sim_sl_dist = 12.0 # Fixed 120-pip max SL
        sim_tp_dist = abs(t.take_profit_1 - t.planned_entry)
        if sim_tp_dist == 0: sim_tp_dist = 15.0 # Fallback
        
        # Fetch M1 rates to simulate precisely
        end_ts = ts_utc + 3600 * 4 # 4 hours forward
        m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, ts_utc, end_ts)
        
        # Fetch M15 for early exit
        m15_df = get_m15_data(ts_utc, end_ts)
        
        pnl_a = 0.0
        pnl_b = 0.0
        
        if m1_rates is not None and len(m1_rates) > 0:
            m1_df = pd.DataFrame(m1_rates)
            
            # Simulate Method A (Standard 120-pip SL)
            for _, row in m1_df.iterrows():
                h, l = row["high"], row["low"]
                if t.direction == "LONG":
                    if l <= t.planned_entry - sim_sl_dist: pnl_a = -sim_sl_dist; break
                    if h >= t.planned_entry + sim_tp_dist: pnl_a = sim_tp_dist; break
                else:
                    if h >= t.planned_entry + sim_sl_dist: pnl_a = -sim_sl_dist; break
                    if l <= t.planned_entry - sim_tp_dist: pnl_a = sim_tp_dist; break
                    
            # Simulate Method B (Early Exit)
            for _, row in m1_df.iterrows():
                h, l = row["high"], row["low"]
                curr_ts = int(row["time"])
                
                # Check normal SL/TP first
                hit_sl = False
                hit_tp = False
                if t.direction == "LONG":
                    if l <= t.planned_entry - sim_sl_dist: hit_sl = True; pnl_b = -sim_sl_dist
                    elif h >= t.planned_entry + sim_tp_dist: hit_tp = True; pnl_b = sim_tp_dist
                else:
                    if h >= t.planned_entry + sim_sl_dist: hit_sl = True; pnl_b = -sim_sl_dist
                    elif l <= t.planned_entry - sim_tp_dist: hit_tp = True; pnl_b = sim_tp_dist
                    
                if hit_sl or hit_tp: break
                
                # Check Early Exit (If an M15 candle closed against us)
                if m15_df is not None:
                    # Find the last completed M15 candle before current M1 time
                    closed_m15 = m15_df[m15_df["time"] < curr_ts]
                    if len(closed_m15) > 0:
                        last_m15 = closed_m15.iloc[-1]
                        m15_close = last_m15["close"]
                        m15_ema20 = last_m15["ema_20"]
                        
                        # Only exit if the close is against us
                        if t.direction == "LONG" and m15_close < m15_ema20:
                            pnl_b = m15_close - t.planned_entry
                            break
                        elif t.direction == "SHORT" and m15_close > m15_ema20:
                            pnl_b = t.planned_entry - m15_close
                            break

        total_a_pnl += pnl_a
        if pnl_a > 0: wins_a += 1
        
        total_b_pnl += pnl_b
        if pnl_b > 0: wins_b += 1
        
        note = ""
        if pnl_a < 0 and pnl_b > pnl_a: note = f"SAVED {pnl_b - pnl_a:+.2f} pts"
        if pnl_a > 0 and pnl_b < 0: note = "KILLED WINNER"
            
        print(f"#{t.id:<7} | {t.direction:<5} | {pnl_a:>10.2f} pts            | {pnl_b:>10.2f} pts            | {note}")

    print("="*110)
    print(f"Method A (120-pip max SL) : Net {total_a_pnl:+.2f} pts | Wins: {wins_a}/{taken_trades}")
    print(f"Method B (Early Exit)     : Net {total_b_pnl:+.2f} pts | Wins: {wins_b}/{taken_trades}")
    print("="*110)

if __name__ == "__main__":
    run()
