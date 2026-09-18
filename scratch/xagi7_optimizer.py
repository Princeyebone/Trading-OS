import sys
import os
import pandas as pd
import MetaTrader5 as mt5
import ta
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine.broker_executor import _init_mt5
from engine.scalping_engine import ScalpingEngine, M1HyperEngine

def simulate_trade(df_m1, entry_idx, direction, entry_price, sl_pips=50.0, lock_pips=20.0, trail_step=10.0):
    sl_price = entry_price - (sl_pips / 10.0) if direction == 'LONG' else entry_price + (sl_pips / 10.0)
    
    highest_profit = 0.0
    locked_profit = 0.0
    
    # 20-min forced close
    max_duration = 20
    
    for i in range(entry_idx + 1, min(entry_idx + 60, len(df_m1))):
        row = df_m1.iloc[i]
        
        # Calculate max adverse excursion for SL hit
        if direction == 'LONG':
            if row['low'] <= sl_price:
                return -(entry_price - sl_price) * 10.0
            
            curr_profit = (row['high'] - entry_price) * 10.0
            close_profit = (row['close'] - entry_price) * 10.0
        else:
            if row['high'] >= sl_price:
                return -(sl_price - entry_price) * 10.0
                
            curr_profit = (entry_price - row['low']) * 10.0
            close_profit = (entry_price - row['close']) * 10.0
            
        if curr_profit > highest_profit:
            highest_profit = curr_profit
            
        # Trailing Logic
        if highest_profit >= lock_pips:
            steps = int((highest_profit - lock_pips) // trail_step)
            new_lock = lock_pips + (steps * trail_step)
            if new_lock > locked_profit:
                locked_profit = new_lock
                sl_price = entry_price + (locked_profit / 10.0) if direction == 'LONG' else entry_price - (locked_profit / 10.0)
        
        # Reversal check
        if locked_profit > 0:
            if direction == 'LONG' and row['low'] <= sl_price:
                return locked_profit
            if direction == 'SHORT' and row['high'] >= sl_price:
                return locked_profit
                
        # 20-min forced close
        if i - entry_idx >= max_duration and close_profit < 0:
            return close_profit
            
    # If still open after 60 mins, just close at current
    final = df_m1.iloc[min(entry_idx + 60, len(df_m1)-1)]
    if direction == 'LONG': return (final['close'] - entry_price) * 10.0
    else: return (entry_price - final['close']) * 10.0

def run_simulation(m5_fast_ema=20, m5_slow_ema=50, sl=50.0):
    if not _init_mt5():
        return
        
    rates_m1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 10000)
    rates_m5 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 2500)
    
    df_m1 = pd.DataFrame(rates_m1)
    df_m1['time_dt'] = pd.to_datetime(df_m1['time'], unit='s')
    
    df_m5 = pd.DataFrame(rates_m5)
    df_m5['time_dt'] = pd.to_datetime(df_m5['time'], unit='s')
    
    # Precompute EMAs on M5
    df_m5['ema_fast'] = ta.trend.ema_indicator(df_m5['close'], window=m5_fast_ema)
    df_m5['ema_slow'] = ta.trend.ema_indicator(df_m5['close'], window=m5_slow_ema)
    
    trades = []
    last_trade_time = pd.to_datetime('2000-01-01')
    
    print(f"Running simulation: EMA {m5_fast_ema}/{m5_slow_ema}, SL {sl}...")
    
    # Start simulating from ~500th M1 candle to ensure enough M5 history
    for i in range(1000, len(df_m1) - 60, 5): # Check every 5 mins to speed up
        current_time = df_m1.iloc[i]['time_dt']
        
        if (current_time - last_trade_time).total_seconds() < 1800: # 30 min cooldown
            continue
            
        m5_subset = df_m5[df_m5['time_dt'] <= current_time]
        if len(m5_subset) < 50: continue
        
        current_m5 = m5_subset.iloc[-1]
        
        # M5 Trend
        if current_m5['ema_fast'] > current_m5['ema_slow']: m5_trend = 'BULLISH'
        elif current_m5['ema_fast'] < current_m5['ema_slow']: m5_trend = 'BEARISH'
        else: m5_trend = 'SIDEWAYS'
        
        if m5_trend == 'SIDEWAYS': continue
        
        # Get Signals
        m5_idx = len(m5_subset) - 1
        m1_subset = df_m1.iloc[max(0, i-50):i+1]
        
        eng_m5 = ScalpingEngine(m5_subset, m5_subset)
        sigs_m5 = eng_m5.scan(m5_idx, h4_trend=m5_trend)
        
        eng_m1 = M1HyperEngine(m1_subset, h4_trend=m5_trend)
        sigs_m1 = eng_m1.scan(len(m1_subset)-1)
        
        all_sigs = sigs_m5 + sigs_m1
        
        # Filter against M5 Trend
        valid_sigs = [s for s in all_sigs if s['direction'] == m5_trend]
        
        if valid_sigs:
            sig = valid_sigs[0] # Take first valid
            entry_price = float(df_m1.iloc[i]['close'])
            pnl = simulate_trade(df_m1, i, sig['direction'], entry_price, sl_pips=sl)
            
            trades.append({
                'time': current_time,
                'direction': sig['direction'],
                'type': sig['type'],
                'pnl': pnl
            })
            last_trade_time = current_time

    # Analyze
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    print(f"Total Trades: {len(trades)}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Total PnL: {total_pnl:.1f} pips")
    
    # Analyze Today (06:30 MT5 to now)
    start_today = pd.to_datetime('2026-07-06 06:30:00')
    today_trades = [t for t in trades if t['time'] >= start_today]
    today_pnl = sum(t['pnl'] for t in today_trades)
    print(f"\n--- TODAY'S CRASH PERIOD ---")
    for t in today_trades:
        print(f"{t['time']} | {t['direction']} {t['type']} | {t['pnl']:+.1f} pips")
    print(f"Today PnL: {today_pnl:+.1f} pips")
    
    return total_pnl, today_pnl

if __name__ == "__main__":
    run_simulation(20, 50, 30.0)
