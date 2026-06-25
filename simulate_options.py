import pandas as pd
import ta
import MetaTrader5 as mt5

def run_simulation():
    if not mt5.initialize():
        print("MT5 init failed")
        return

    symbol = "XAUUSD"
    print("Fetching historical M15 data...")
    # Fetch 5000 M15 candles (~2 months)
    m15_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 5000)
    
    print("Fetching historical M1 data...")
    # Fetch enough M1 candles to cover the same period
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

    # -------------------------------------------------------------
    # OPTION A: TRUE SMC (FVG + ORDER BLOCK)
    # -------------------------------------------------------------
    print("Extracting True SMC (FVG) signals...")
    smc_signals = []
    
    # We need 3 candles to confirm an FVG. i-2 (OB), i-1 (Impulse), i (Gap Confirmation)
    for i in range(200, len(df_m15)):
        c_confirm = df_m15.iloc[i]
        c_impulse = df_m15.iloc[i-1]
        c_ob = df_m15.iloc[i-2]
        
        is_bullish_trend = c_confirm['close'] > c_confirm['ema200']
        
        if is_bullish_trend:
            # Bullish FVG check
            # OB must be bearish, impulse bullish and engulfing
            if c_ob['close'] < c_ob['open'] and c_impulse['close'] > c_impulse['open'] and c_impulse['close'] > c_ob['high']:
                # FVG check: c_confirm's LOW must be higher than c_ob's HIGH
                if c_confirm['low'] > c_ob['high']:
                    gap_size = c_confirm['low'] - c_ob['high']
                    if gap_size >= 0.5: # 5 pips minimum gap
                        smc_signals.append({
                            "time": c_confirm['time'],
                            "direction": "LONG",
                            "entry": c_ob['high'], # Enter at the top of the OB
                            "ob_high": c_ob['high'],
                            "ob_low": c_ob['low']
                        })
        else:
            # Bearish FVG check
            # OB must be bullish, impulse bearish and engulfing
            if c_ob['close'] > c_ob['open'] and c_impulse['close'] < c_impulse['open'] and c_impulse['close'] < c_ob['low']:
                # FVG check: c_confirm's HIGH must be lower than c_ob's LOW
                if c_confirm['high'] < c_ob['low']:
                    gap_size = c_ob['low'] - c_confirm['high']
                    if gap_size >= 0.5:
                        smc_signals.append({
                            "time": c_confirm['time'],
                            "direction": "SHORT",
                            "entry": c_ob['low'], # Enter at the bottom of the OB
                            "ob_high": c_ob['high'],
                            "ob_low": c_ob['low']
                        })
                        
    # -------------------------------------------------------------
    # OPTION B: M15 MOMENTUM SIBLING
    # -------------------------------------------------------------
    print("Extracting M15 Momentum signals...")
    mom_signals = []
    for i in range(200, len(df_m15)):
        c1 = df_m15.iloc[i-2]
        c2 = df_m15.iloc[i-1]
        
        is_c1_bearish = c1['close'] < c1['open']
        is_c2_bullish = c2['close'] > c2['open']
        
        is_c1_bullish = c1['close'] > c1['open']
        is_c2_bearish = c2['close'] < c2['open']
        
        c2_range = c2['high'] - c2['low']
        
        if is_c1_bearish and is_c2_bullish and c2['close'] > c1['high'] and c2_range >= 2.0: # 20 pips impulse
            limit_price = c2['low'] + (c2_range * 0.5)
            sl_price = c2['low'] - 1.0 # 10 pips below impulse low
            mom_signals.append({
                "time": df_m15.iloc[i]['time'],
                "direction": "LONG",
                "entry": limit_price,
                "sl": sl_price
            })
        elif is_c1_bullish and is_c2_bearish and c2['close'] < c1['low'] and c2_range >= 2.0:
            limit_price = c2['high'] - (c2_range * 0.5)
            sl_price = c2['high'] + 1.0
            mom_signals.append({
                "time": df_m15.iloc[i]['time'],
                "direction": "SHORT",
                "entry": limit_price,
                "sl": sl_price
            })

    print(f"Generated {len(smc_signals)} SMC signals and {len(mom_signals)} Momentum signals.")
    
    # -------------------------------------------------------------
    # RUN M1 PATHING ENGINE
    # -------------------------------------------------------------
    
    # We will test SMC with a 50p SL buffer and 100p trail (needs room to breathe)
    # We will test Momentum with its native SL and a 30p trail
    
    configs = [
        {"name": "Option A: True SMC (FVG + OB) | Wide SL, 100p Trail", "type": "smc", "signals": smc_signals, "trail": 100.0},
        {"name": "Option B: M15 Momentum Sibling | Tight SL, 30p Trail", "type": "mom", "signals": mom_signals, "trail": 30.0}
    ]
    
    results = {c['name']: {"trades": 0, "wins": 0, "losses": 0, "pips": 0.0} for c in configs}

    for config in configs:
        active_trade = None
        pending_order = None
        signal_idx = 0
        signals = config['signals']
        trail = config['trail']
        
        for i in range(len(df_m1)):
            m1_time = df_m1.index[i]
            c = df_m1.iloc[i]
            
            while signal_idx < len(signals) and signals[signal_idx]['time'] <= m1_time:
                sig = signals[signal_idx]
                if not active_trade:
                    if config['type'] == "smc":
                        sl_dist_pips = (sig['ob_high'] - sig['ob_low']) * 10 + 30.0 # 30 pip buffer
                        sl_price = sig['entry'] - (sl_dist_pips / 10.0) if sig['direction'] == "LONG" else sig['entry'] + (sl_dist_pips / 10.0)
                    else:
                        sl_price = sig['sl']
                        
                    pending_order = {
                        'direction': sig['direction'],
                        'entry': sig['entry'],
                        'sl': sl_price,
                        'highest_profit': 0.0,
                        'locked': 0.0
                    }
                signal_idx += 1
                
            if pending_order and not active_trade:
                if pending_order['direction'] == "LONG" and c['low'] <= pending_order['entry']:
                    active_trade = pending_order.copy()
                    pending_order = None
                elif pending_order['direction'] == "SHORT" and c['high'] >= pending_order['entry']:
                    active_trade = pending_order.copy()
                    pending_order = None
                    
            if active_trade:
                dir = active_trade['direction']
                entry = active_trade['entry']
                sl = active_trade['sl']
                
                if dir == "LONG":
                    if c['low'] <= sl:
                        results[config['name']]['trades'] += 1
                        if active_trade.get('locked', 0) > 0:
                            results[config['name']]['wins'] += 1
                        else:
                            results[config['name']]['losses'] += 1
                        results[config['name']]['pips'] += (sl - entry) * 10
                        active_trade = None
                        continue
                        
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
                        
                    profit_pips = (entry - c['low']) * 10
                    if profit_pips > active_trade['highest_profit']:
                        active_trade['highest_profit'] = profit_pips
                        
                    if active_trade['highest_profit'] >= trail:
                        new_locked = active_trade['highest_profit'] - trail
                        if new_locked > active_trade['locked']:
                            active_trade['locked'] = new_locked
                            active_trade['sl'] = entry - (active_trade['locked'] / 10.0)

    print("\n--- HIGH FIDELITY SIMULATION RESULTS ---")
    for name, res in results.items():
        print(f"\n{name}")
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
