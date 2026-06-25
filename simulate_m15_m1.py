import pandas as pd
import ta
import MetaTrader5 as mt5
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.pattern_detector import detect_order_blocks

def run_simulation():
    if not mt5.initialize():
        print("MT5 init failed")
        return

    symbol = "XAUUSD"
    print("Fetching historical M15 data...")
    # Fetch 5000 M15 candles (~2 months)
    m15_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 5000)
    
    print("Fetching historical M1 data...")
    # Fetch enough M1 candles to cover the same period (5000 * 15 = 75000)
    m1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 80000)
    
    if m15_rates is None or m1_rates is None:
        print("Failed to fetch rates")
        return
        
    df_m15 = pd.DataFrame(m15_rates)
    df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')
    df_m15['ema200'] = ta.trend.ema_indicator(df_m15['close'], window=200)
    
    df_m1 = pd.DataFrame(m1_rates)
    df_m1['time'] = pd.to_datetime(df_m1['time'], unit='s')
    df_m1.set_index('time', inplace=True)
    
    print("Pre-processing complete. Starting high-fidelity simulation...")
    
    # Let's test a few configurations:
    configs = [
        {"name": "Tight SL + 30p Trail (Current)", "sl_buf": 10.0, "trail": 30.0},
        {"name": "Medium SL + 50p Trail", "sl_buf": 20.0, "trail": 50.0},
        {"name": "Wide SL + 100p Trail", "sl_buf": 35.0, "trail": 100.0},
        {"name": "Wide SL + Fixed 150p TP", "sl_buf": 35.0, "trail": None, "tp": 150.0}
    ]
    
    results = {c['name']: {"trades": 0, "wins": 0, "losses": 0, "pips": 0.0} for c in configs}
    
    # Pre-calculate Order Blocks at each M15 step to avoid running it 4 times
    # We will generate a list of trading signals
    signals = []
    
    # We skip first 200 to let EMA warm up
    for i in range(200, len(df_m15)):
        current_c = df_m15.iloc[i]
        
        is_bullish = current_c['close'] > current_c['ema200']
        target_dir = 'BULLISH' if is_bullish else 'BEARISH'
        
        window_df = df_m15.iloc[i-40:i].reset_index(drop=True)
        df_filter = "long" if is_bullish else "short"
        obs = detect_order_blocks(window_df, direction=df_filter)
        
        valid_obs = [ob for ob in obs if ob['direction'] == target_dir]
        if valid_obs:
            ob = valid_obs[0]
            limit_price = ob['high'] if is_bullish else ob['low']
            signals.append({
                "time": current_c['time'],
                "direction": "LONG" if is_bullish else "SHORT",
                "entry": limit_price,
                "ob_high": ob['high'],
                "ob_low": ob['low']
            })
            
    print(f"Generated {len(signals)} M15 signals. Running M1 pathing...")

    for config in configs:
        active_trade = None
        pending_order = None
        signal_idx = 0
        
        sl_buf = config['sl_buf']
        trail = config['trail']
        fixed_tp = config.get('tp', None)
        
        # Iterate through M1 data minute by minute
        for i in range(len(df_m1)):
            m1_time = df_m1.index[i]
            c = df_m1.iloc[i]
            
            # Check if a new M15 signal arrived
            while signal_idx < len(signals) and signals[signal_idx]['time'] <= m1_time:
                sig = signals[signal_idx]
                if not active_trade:
                    # Place pending order
                    sl_dist_pips = (sig['ob_high'] - sig['ob_low']) * 10 + sl_buf
                    sl_dist_pips = max(15.0, min(80.0, sl_dist_pips))
                    
                    sl_price = sig['entry'] - (sl_dist_pips / 10.0) if sig['direction'] == "LONG" else sig['entry'] + (sl_dist_pips / 10.0)
                    
                    pending_order = {
                        'direction': sig['direction'],
                        'entry': sig['entry'],
                        'sl': sl_price,
                        'highest_profit': 0.0,
                        'locked': 0.0,
                        'tp': sig['entry'] + (fixed_tp/10.0) if sig['direction'] == "LONG" and fixed_tp else (sig['entry'] - (fixed_tp/10.0) if fixed_tp else None)
                    }
                signal_idx += 1
                
            # 1. Check if pending order gets hit
            if pending_order and not active_trade:
                if pending_order['direction'] == "LONG" and c['low'] <= pending_order['entry']:
                    # Triggered LONG
                    active_trade = pending_order.copy()
                    pending_order = None
                elif pending_order['direction'] == "SHORT" and c['high'] >= pending_order['entry']:
                    # Triggered SHORT
                    active_trade = pending_order.copy()
                    pending_order = None
                    
            # 2. Process Active Trade
            if active_trade:
                dir = active_trade['direction']
                entry = active_trade['entry']
                sl = active_trade['sl']
                tp = active_trade['tp']
                
                if dir == "LONG":
                    # Did we hit SL?
                    if c['low'] <= sl:
                        results[config['name']]['trades'] += 1
                        if active_trade.get('locked', 0) > 0:
                            results[config['name']]['wins'] += 1
                        else:
                            results[config['name']]['losses'] += 1
                        results[config['name']]['pips'] += (sl - entry) * 10
                        active_trade = None
                        continue
                        
                    # Did we hit fixed TP?
                    if tp and c['high'] >= tp:
                        results[config['name']]['trades'] += 1
                        results[config['name']]['wins'] += 1
                        results[config['name']]['pips'] += (tp - entry) * 10
                        active_trade = None
                        continue
                        
                    # Calculate Profit for trailing
                    if trail:
                        profit_pips = (c['high'] - entry) * 10
                        if profit_pips > active_trade['highest_profit']:
                            active_trade['highest_profit'] = profit_pips
                            
                        if active_trade['highest_profit'] >= trail:
                            new_locked = active_trade['highest_profit'] - trail
                            if new_locked > active_trade['locked']:
                                active_trade['locked'] = new_locked
                                active_trade['sl'] = entry + (active_trade['locked'] / 10.0)
                                
                elif dir == "SHORT":
                    if c['high'] >= sl:
                        results[config['name']]['trades'] += 1
                        if active_trade.get('locked', 0) > 0:
                            results[config['name']]['wins'] += 1
                        else:
                            results[config['name']]['losses'] += 1
                        results[config['name']]['pips'] += (entry - sl) * 10
                        active_trade = None
                        continue
                        
                    if tp and c['low'] <= tp:
                        results[config['name']]['trades'] += 1
                        results[config['name']]['wins'] += 1
                        results[config['name']]['pips'] += (entry - tp) * 10
                        active_trade = None
                        continue
                        
                    if trail:
                        profit_pips = (entry - c['low']) * 10
                        if profit_pips > active_trade['highest_profit']:
                            active_trade['highest_profit'] = profit_pips
                            
                        if active_trade['highest_profit'] >= trail:
                            new_locked = active_trade['highest_profit'] - trail
                            if new_locked > active_trade['locked']:
                                active_trade['locked'] = new_locked
                                active_trade['sl'] = entry - (active_trade['locked'] / 10.0)

    print("\n--- HIGH FIDELITY M15 SMC BACKTEST RESULTS ---")
    for name, res in results.items():
        print(f"\nConfiguration: {name}")
        t = res['trades']
        w = res['wins']
        l = res['losses']
        p = res['pips']
        print(f"Total Trades: {t}")
        if t > 0:
            print(f"Wins: {w} | Losses: {l}")
            print(f"Win Rate: {(w/t)*100:.2f}%")
            print(f"Net Pips: {p:.1f}")
            print(f"Average Pips/Trade: {p/t:.2f}")

run_simulation()
