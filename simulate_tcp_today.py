"""
simulate_tcp_today.py
Simulates TCP signals for today on M15.
Tests Option A (Strict H4 Gate) vs Option B (Bypass H4 Gate for Crown Momentum).
"""

import sys, os
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

from engine.rule_engine import evaluate_all
from engine.data_fetcher import fetch_ohlcv
import ta

def get_trend(data: pd.DataFrame, current_idx: int):
    df = data.iloc[:current_idx+1].copy()
    if len(df) < 50: return "UNKNOWN"
    ema20 = ta.trend.ema_indicator(df["close"], window=20).iloc[-1]
    ema50 = ta.trend.ema_indicator(df["close"], window=50).iloc[-1]
    if ema20 > ema50: return "BULLISH"
    if ema20 < ema50: return "BEARISH"
    return "MIXED"

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    # Fetch data for today
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # We need some history for indicators
    m15_rates = mt5.copy_rates_from("XAUUSD", mt5.TIMEFRAME_M15, now, 200)
    h1_rates = mt5.copy_rates_from("XAUUSD", mt5.TIMEFRAME_H1, now, 200)
    h4_rates = mt5.copy_rates_from("XAUUSD", mt5.TIMEFRAME_H4, now, 200)
    
    m15_df = pd.DataFrame(m15_rates)
    h1_df = pd.DataFrame(h1_rates)
    h4_df = pd.DataFrame(h4_rates)
    
    m15_df['time'] = pd.to_datetime(m15_df['time'], unit='s', utc=True)
    h1_df['time'] = pd.to_datetime(h1_df['time'], unit='s', utc=True)
    h4_df['time'] = pd.to_datetime(h4_df['time'], unit='s', utc=True)
    
    today_start_idx = m15_df[m15_df['time'] >= start_of_day].index.min()
    
    results_a = []
    results_b = []

    print("\n" + "="*115)
    print(f"{'Time':<20} | {'Dir':<5} | {'Score':<5} | {'H4':<8} | {'Reason':<20} | {'Strict (A)':<12} | {'Bypass (B)':<12}")
    print("="*115)

    for i in range(today_start_idx, len(m15_df) - 1):
        ts = m15_df['time'].iloc[i]
        
        # Prepare historical data slices up to this candle
        current_m15 = m15_df.iloc[:i+1].copy()
        current_h1 = h1_df[h1_df['time'] <= ts].copy()
        current_h4 = h4_df[h4_df['time'] <= ts].copy()
        
        timeframes = {
            "M15": current_m15,
            "H1": current_h1,
            "H4": current_h4
        }
        
        signal = evaluate_all(timeframes)
        
        if signal.get('verdict') == 'TRADE':
            direction = signal['direction']
            reason = signal.get('reason', '')
            score = signal.get('confidence', 0)
            
            h4_trend = get_trend(h4_df, len(current_h4)-1)
            
            is_crown = "CROWN_MOMENTUM" in reason
            
            # Option A: Strict H4 Gate
            take_a = True
            if direction == "LONG" and h4_trend == "BEARISH": take_a = False
            if direction == "SHORT" and h4_trend == "BULLISH": take_a = False
                
            # Option B: Bypass H4 Gate if Crown
            take_b = True
            if direction == "LONG" and h4_trend == "BEARISH" and not is_crown: take_b = False
            if direction == "SHORT" and h4_trend == "BULLISH" and not is_crown: take_b = False
                
            str_a = "TAKEN" if take_a else "BLOCKED"
            str_b = "TAKEN" if take_b else "BLOCKED"
            
            # Print row
            short_reason = reason.split("|")[-1] if "|" in reason else reason
            print(f"{ts.strftime('%H:%M')} | {direction:<5} | {score:<5} | {h4_trend:<8} | {short_reason:<20} | {str_a:<12} | {str_b:<12}")
            
            # Simulate PnL
            entry = signal['entry']
            sl = signal['sl']
            tp1 = signal['tp1']
            
            # Get M1 forward rates to resolve trade
            m1_rates = mt5.copy_rates_from("XAUUSD", mt5.TIMEFRAME_M1, ts + timedelta(hours=4), 240)
            if m1_rates is not None and len(m1_rates) > 0:
                m1_df = pd.DataFrame(m1_rates)
                m1_df = m1_df[m1_df['time'] > ts.timestamp()]
                
                pnl = 0.0
                for _, row in m1_df.iterrows():
                    h, l = row["high"], row["low"]
                    if direction == "LONG":
                        if l <= sl: pnl = sl - entry; break
                        if h >= tp1: pnl = tp1 - entry; break
                    else:
                        if h >= sl: pnl = entry - sl; break
                        if l <= tp1: pnl = entry - tp1; break
                        
                if take_a and pnl != 0: results_a.append(pnl)
                if take_b and pnl != 0: results_b.append(pnl)

    print("="*115)
    
    net_a = sum(results_a)
    wins_a = sum(1 for p in results_a if p > 0)
    
    net_b = sum(results_b)
    wins_b = sum(1 for p in results_b if p > 0)
    
    print(f"Option A (Strict H4)  : Net {net_a:+.2f} pts | Wins: {wins_a}/{len(results_a)}")
    print(f"Option B (Crown Bypass): Net {net_b:+.2f} pts | Wins: {wins_b}/{len(results_b)}")

if __name__ == "__main__":
    run()
