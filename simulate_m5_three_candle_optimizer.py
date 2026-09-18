import sys
import os
import itertools
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_optimizer():
    from dotenv import load_dotenv
    load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")
    
    login = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")
    
    if not mt5.initialize(login=login, password=password, server=server):
        print("MT5 Init Failed:", mt5.last_error())
        return

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=60) # 60 days of data
    
    print("Fetching M1 and M5 data for the last 60 days...")
    m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, start_time, now)
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_time, now)
    
    if m1_rates is None or m5_rates is None:
        print("Failed to fetch data")
        return
        
    m1_df = pd.DataFrame(m1_rates)
    m1_df['time'] = pd.to_datetime(m1_df['time'], unit='s', utc=True)
    m1_df.set_index('time', inplace=True)
    
    m5_df = pd.DataFrame(m5_rates)
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    m5_df.set_index('time', inplace=True)

    # Param grid
    body_sizes = [0.0, 0.5, 1.0, 1.5] # 0, 5, 10, 15 pips
    sl_types = ["FIXED_20", "FIXED_30", "C2_LOW_5", "C2_LOW_10"]
    tp_types = ["RR_1.0", "RR_1.5", "RR_2.0", "TRAIL_20", "TRAIL_30", "TRAIL_40"]
    
    results = []
    
    print("Generating setups...")
    # Pre-calculate base setups to save time
    base_setups = []
    
    for i in range(2, len(m5_df) - 1):
        c1 = m5_df.iloc[i-2]
        c2 = m5_df.iloc[i-1]
        c3 = m5_df.iloc[i] # The entry candle
        
        c1_body = c1['close'] - c1['open']
        c2_body = c2['close'] - c2['open']
        
        direction = None
        min_body = min(abs(c1_body), abs(c2_body))
        
        if c1_body > 0 and c2_body > 0:
            direction = "LONG"
        elif c1_body < 0 and c2_body < 0:
            direction = "SHORT"
            
        if direction:
            future_m1 = m1_df[m1_df.index >= m5_df.index[i]].head(300)
            base_setups.append({
                'time': m5_df.index[i],
                'direction': direction,
                'min_body': min_body,
                'c2_low': c2['low'],
                'c2_high': c2['high'],
                'entry_price': c3['open'],
                'm1_lows': future_m1['low'].values,
                'm1_highs': future_m1['high'].values,
                'm1_closes': future_m1['close'].values,
                'm1_len': len(future_m1)
            })
            
    print(f"Found {len(base_setups)} potential raw setups.")
    print("Running grid search...")
    
    total_combinations = len(body_sizes) * len(sl_types) * len(tp_types)
    count = 0
    
    for body, sl_type, tp_type in itertools.product(body_sizes, sl_types, tp_types):
        count += 1
        
        wins = 0
        losses = 0
        total_pnl = 0.0
        trade_count = 0
        
        for setup in base_setups:
            if setup['min_body'] < body:
                continue
                
            trade_count += 1
            direction = setup['direction']
            entry_price = setup['entry_price']
            
            # Calculate SL
            if sl_type == "FIXED_20": sl = entry_price - 2.0 if direction == "LONG" else entry_price + 2.0
            elif sl_type == "FIXED_30": sl = entry_price - 3.0 if direction == "LONG" else entry_price + 3.0
            elif sl_type == "C2_LOW_5": sl = setup['c2_low'] - 0.5 if direction == "LONG" else setup['c2_high'] + 0.5
            elif sl_type == "C2_LOW_10": sl = setup['c2_low'] - 1.0 if direction == "LONG" else setup['c2_high'] + 1.0
            
            risk = abs(entry_price - sl)
            # Filter out trades with massive risk (e.g., > 5.0 points) to avoid anomalies
            if risk > 5.0 or risk <= 0:
                trade_count -= 1
                continue
                
            # Calculate TP if fixed
            tp_price = 0.0
            if "RR_" in tp_type:
                rr_multiplier = float(tp_type.split("_")[1])
                tp_price = entry_price + (risk * rr_multiplier) if direction == "LONG" else entry_price - (risk * rr_multiplier)
                
            is_trailing = "TRAIL" in tp_type
            trail_pips = float(tp_type.split("_")[1]) if is_trailing else 0.0
            
            # Convert to numpy for fast iteration
            lows = setup['m1_lows']
            highs = setup['m1_highs']
            closes = setup['m1_closes']
            m1_len = setup['m1_len']
            
            highest_profit = 0.0
            locked_profit = 0.0
            trade_pnl = 0.0
            closed = False
            
            for k in range(m1_len):
                if direction == "LONG":
                    current_profit = (closes[k] - entry_price) * 10.0
                    if lows[k] <= sl:
                        trade_pnl = (sl - entry_price) * 10.0
                        closed = True
                        break
                    if tp_price > 0 and highs[k] >= tp_price:
                        trade_pnl = (tp_price - entry_price) * 10.0
                        closed = True
                        break
                else:
                    current_profit = (entry_price - closes[k]) * 10.0
                    if highs[k] >= sl:
                        trade_pnl = (entry_price - sl) * 10.0
                        closed = True
                        break
                    if tp_price > 0 and lows[k] <= tp_price:
                        trade_pnl = (entry_price - tp_price) * 10.0
                        closed = True
                        break
                        
                if current_profit > highest_profit:
                    highest_profit = current_profit
                    
                if is_trailing and highest_profit >= trail_pips:
                    trail = highest_profit - trail_pips
                    if trail > locked_profit:
                        locked_profit = trail
                        
                if locked_profit > 0 and current_profit <= locked_profit:
                    trade_pnl = locked_profit
                    closed = True
                    break
                    
            if not closed:
                trade_pnl = current_profit
                
            if trade_pnl > 0: wins += 1
            else: losses += 1
            total_pnl += trade_pnl
            
        win_rate = (wins / max(1, wins+losses)) * 100
        results.append({
            'body': body,
            'sl_type': sl_type,
            'tp_type': tp_type,
            'trades': trade_count,
            'win_rate': win_rate,
            'pnl': total_pnl
        })
        if count % 20 == 0:
            print(f"Processed {count}/{total_combinations} combinations...")
            
    print("\n" + "="*50)
    print("TOP 5 BY PNL:")
    sorted_by_pnl = sorted(results, key=lambda x: x['pnl'], reverse=True)
    for r in sorted_by_pnl[:5]:
        print(f"Body: {r['body']:<4} | SL: {r['sl_type']:<12} | TP: {r['tp_type']:<10} | Trades: {r['trades']:<4} | WR: {r['win_rate']:>5.1f}% | PnL: {r['pnl']:>7.1f} pips")
        
    print("\n" + "="*50)
    print("TOP 5 BY WIN RATE (min 20 trades):")
    valid_wr = [r for r in results if r['trades'] >= 20]
    sorted_by_wr = sorted(valid_wr, key=lambda x: x['win_rate'], reverse=True)
    for r in sorted_by_wr[:5]:
        print(f"Body: {r['body']:<4} | SL: {r['sl_type']:<12} | TP: {r['tp_type']:<10} | Trades: {r['trades']:<4} | WR: {r['win_rate']:>5.1f}% | PnL: {r['pnl']:>7.1f} pips")

if __name__ == "__main__":
    run_optimizer()
