import sys
import os
import pandas as pd
import MetaTrader5 as mt5
import ta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine.broker_executor import _init_mt5
from engine.scalping_engine import ScalpingEngine

def get_h1_trend(df_h1, current_time):
    # Get H1 data up to current_time
    past_h1 = df_h1[df_h1['time'] <= current_time]
    if len(past_h1) < 5: return "UNKNOWN"
    closes = past_h1['close'].values
    if closes[-1] > closes[-3]: return "BULLISH"
    elif closes[-1] < closes[-3]: return "BEARISH"
    return "SIDEWAYS"

def detect_waterfall_crash(m5_data, current_idx):
    if current_idx < 10: return None, None
    
    # Need 3 consecutive strong bearish candles
    c0 = m5_data.iloc[current_idx]
    c1 = m5_data.iloc[current_idx-1]
    c2 = m5_data.iloc[current_idx-2]
    
    is_bearish = lambda c: c['close'] < c['open']
    
    # Detect 2-candle momentum crash
    if is_bearish(c0) and is_bearish(c1):
        total_drop = (c1['open'] - c0['close'])
        if total_drop >= 4.0: # 40 pips in 10 mins
            # Check volume spike
            avg_vol = m5_data['tick_volume'].iloc[current_idx-20:current_idx].mean()
            if c0['tick_volume'] > avg_vol * 1.2 or c1['tick_volume'] > avg_vol * 1.2:
                # Calculate RSI to make sure we aren't selling the absolute bottom
                rsi = ta.momentum.rsi(m5_data['close'].iloc[:current_idx+1], 14).iloc[-1]
                if rsi > 20: # If RSI is < 20, it's too late to short
                    return 'BEARISH', {
                        'setup_type': 'WATERFALL_CRASH',
                        'drop_size': round(total_drop, 2),
                        'rsi': round(rsi, 2)
                    }
    return None, None

def check_circuit_breaker(m5_data, current_idx):
    if current_idx < 10: return False
    
    # Check 30-min momentum (6 candles)
    current_close = m5_data['close'].iloc[current_idx]
    past_close = m5_data['close'].iloc[current_idx-6]
    
    drop = past_close - current_close
    
    ema20 = m5_data['close'].rolling(20).mean().iloc[current_idx]
    
    if drop > 5.0 and current_close < ema20:
        return True # Circuit breaker TRIPPED -> Block all longs
    return False

def simulate():
    if not _init_mt5():
        print("Failed MT5 init")
        return
        
    rates_m5 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 1000)
    rates_h1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 500)
    
    df_m5 = pd.DataFrame(rates_m5)
    df_m5['time'] = pd.to_datetime(df_m5['time'], unit='s')
    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    
    # We want to simulate today from 09:00 MT5 time to 11:30 MT5 time
    start_time = pd.to_datetime('2026-07-06 09:00:00')
    end_time = pd.to_datetime('2026-07-06 11:30:00')
    
    sim_df = df_m5[(df_m5['time'] >= start_time) & (df_m5['time'] <= end_time)]
    
    print("=== WATERFALL CRASH SIMULATION ===")
    print("Simulating XAGI4 with Circuit Breaker + Waterfall Logic")
    
    trades_taken = []
    
    for i in range(len(sim_df)):
        current_time = sim_df.iloc[i]['time']
        idx = sim_df.index[i]
        
        # Original XAGI4 Logic
        engine = ScalpingEngine(df_m5.iloc[:idx+1], df_m5.iloc[:idx+1])
        original_signals = engine.scan(idx, h4_trend="UNKNOWN")
        
        # New Logic
        h1_trend = get_h1_trend(df_h1, current_time)
        cb_tripped = check_circuit_breaker(df_m5, idx)
        waterfall_dir, waterfall_det = detect_waterfall_crash(df_m5, idx)
        
        all_signals = original_signals.copy()
        if waterfall_dir:
            sig = {
                'type': 'WATERFALL_CRASH',
                'direction': waterfall_dir,
                'details': waterfall_det,
                'timestamp': current_time,
                'price': float(df_m5['close'].iloc[idx])
            }
            # Manually apply SL/TP for waterfall
            entry = sig['price'] - 0.1
            sl = entry + 3.0 # Strict 30 pip SL for waterfall
            tp1 = entry - 6.0
            sig.update({'entry': entry, 'sl': sl, 'tp1': tp1, 'rr': 2.0})
            all_signals.append(sig)
            
        for sig in all_signals:
            if sig.get('verdict') == 'WAIT': continue
            
            # --- APPLY NEW FILTERS ---
            if sig['direction'] == 'BULLISH' and cb_tripped:
                print(f"[{current_time}] 🛑 BLOCKED FALSE BUY: Circuit Breaker active! Dropped > 50 pips recently.")
                continue
                
            if sig['direction'] == 'BEARISH' and h1_trend == 'BULLISH':
                if sig['type'] == 'WATERFALL_CRASH':
                    print(f"[{current_time}] 🚀 H1 FILTER BYPASS: Executing WATERFALL_CRASH Short!")
                else:
                    # Normal blocked short
                    continue
                    
            if sig['direction'] == 'BULLISH' and h1_trend == 'BEARISH':
                continue
                
            # If we pass filters, take trade
            print(f"[{current_time}] ✅ TRADE EXECUTED: {sig['direction']} {sig['type']} @ {sig['entry']:.2f} | SL: {sig['sl']:.2f} | TP: {sig['tp1']:.2f}")
            trades_taken.append({
                'time': current_time,
                'direction': sig['direction'],
                'type': sig['type'],
                'entry': sig['entry'],
                'sl': sig['sl'],
                'tp1': sig['tp1']
            })

    print("\n=== TRADE OUTCOMES (Simulated) ===")
    net_pips = 0.0
    for t in trades_taken:
        # Find outcome
        outcome = "OPEN"
        pips = 0.0
        future = df_m5[df_m5['time'] > t['time']]
        for _, row in future.iterrows():
            if t['direction'] == 'LONG':
                if row['low'] <= t['sl']:
                    outcome = "LOSS"
                    pips = -(t['entry'] - t['sl']) * 10
                    break
                if row['high'] >= t['tp1']:
                    outcome = "WIN"
                    pips = (t['tp1'] - t['entry']) * 10
                    break
            else:
                if row['high'] >= t['sl']:
                    outcome = "LOSS"
                    pips = -(t['sl'] - t['entry']) * 10
                    break
                if row['low'] <= t['tp1']:
                    outcome = "WIN"
                    pips = (t['entry'] - t['tp1']) * 10
                    break
                    
        if outcome == "OPEN":
            current_price = df_m5.iloc[-1]['close']
            if t['direction'] == 'LONG': pips = (current_price - t['entry']) * 10
            else: pips = (t['entry'] - current_price) * 10
            
        print(f"{t['time']} | {t['direction']} {t['type']} | {outcome} | {pips:+.1f} pips")
        net_pips += pips
        
    print(f"\nNet Simulated Performance: {net_pips:+.1f} pips")

if __name__ == "__main__":
    simulate()
