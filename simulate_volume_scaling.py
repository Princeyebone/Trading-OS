import pandas as pd
import ta
import MetaTrader5 as mt5

def run_scaling_simulation():
    if not mt5.initialize():
        print("MT5 init failed")
        return

    symbol = "XAUUSD"
    print("Fetching historical M15 data for baseline trades...")
    m15_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 5000)
    m1_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 80000)
    
    if m15_rates is None or m1_rates is None:
        print("Failed to fetch rates")
        return
        
    df_m15 = pd.DataFrame(m15_rates)
    df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')
    
    df_m1 = pd.DataFrame(m1_rates)
    df_m1['time'] = pd.to_datetime(df_m1['time'], unit='s')
    df_m1.set_index('time', inplace=True)
    
    print("Extracting M15 Scalper (Momentum Sibling) signals...")
    mom_signals = []
    for i in range(200, len(df_m15)):
        c1 = df_m15.iloc[i-2]
        c2 = df_m15.iloc[i-1]
        
        is_c1_bearish = c1['close'] < c1['open']
        is_c2_bullish = c2['close'] > c2['open']
        
        is_c1_bullish = c1['close'] > c1['open']
        is_c2_bearish = c2['close'] < c2['open']
        
        c2_range = c2['high'] - c2['low']
        
        if is_c1_bearish and is_c2_bullish and c2['close'] > c1['high'] and c2_range >= 2.0:
            limit_price = c2['low'] + (c2_range * 0.5)
            sl_price = c2['low'] - 1.0 # 10 pip buffer
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

    print("Running high-fidelity tick simulation to build trade sequence...")
    
    # We will record the exact outcome (pips and sl distance) of every triggered trade
    trades_executed = []
    
    active_trade = None
    pending_order = None
    signal_idx = 0
    signals = mom_signals
    
    trail = 30.0 # 30 pips
    hard_tp = 30.0 # 30 pips hard TP (simulate the new behavior)
    
    for i in range(len(df_m1)):
        m1_time = df_m1.index[i]
        c = df_m1.iloc[i]
        
        while signal_idx < len(signals) and signals[signal_idx]['time'] <= m1_time:
            sig = signals[signal_idx]
            if not active_trade:
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
            
            # SL distance for lot sizing
            sl_dist_pips = abs(entry - sig['sl']) * 10.0
            sl_dist_pips = max(10.0, min(50.0, sl_dist_pips))
            
            if dir == "LONG":
                # Check Hard TP first
                if c['high'] >= entry + 3.0:
                    trades_executed.append({"pips": 30.0, "sl_dist_pips": sl_dist_pips})
                    active_trade = None
                    continue
                    
                if c['low'] <= sl:
                    if active_trade.get('locked', 0) > 0:
                        trades_executed.append({"pips": active_trade['locked'], "sl_dist_pips": sl_dist_pips})
                    else:
                        trades_executed.append({"pips": (sl - entry) * 10, "sl_dist_pips": sl_dist_pips})
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
                if c['low'] <= entry - 3.0:
                    trades_executed.append({"pips": 30.0, "sl_dist_pips": sl_dist_pips})
                    active_trade = None
                    continue
                    
                if c['high'] >= sl:
                    if active_trade.get('locked', 0) > 0:
                        trades_executed.append({"pips": active_trade['locked'], "sl_dist_pips": sl_dist_pips})
                    else:
                        trades_executed.append({"pips": (entry - sl) * 10, "sl_dist_pips": sl_dist_pips})
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

    print(f"\nExtracted {len(trades_executed)} actual market executions with Hard TP applied.")
    
    # Simulate different risk profiles
    risks = [1.0, 2.0, 3.0, 5.0, 10.0]
    initial_balance = 10000.0
    
    print("\n--- SCALING VOLUME SIMULATION (Starting Balance: $10,000) ---")
    
    for risk_pct in risks:
        balance = initial_balance
        peak_balance = initial_balance
        max_drawdown_pct = 0.0
        max_drawdown_dollars = 0.0
        
        wins = 0
        losses = 0
        
        for t in trades_executed:
            risk_dollars = balance * (risk_pct / 100.0)
            # 1 standard lot = $10 per pip. 
            pip_value_per_standard = 10.0
            
            raw_lots = risk_dollars / (t['sl_dist_pips'] * pip_value_per_standard)
            lot_size = max(0.01, round(raw_lots - (raw_lots % 0.01), 2))
            
            # Profit/loss in dollars = pip_value * lots * pips
            # Wait, standard lot = $10/pip. 0.01 lot = $0.10/pip.
            # So PnL = (t['pips']) * (lot_size * 10.0)
            trade_pnl = t['pips'] * (lot_size * 10.0)
            
            balance += trade_pnl
            
            if trade_pnl > 0:
                wins += 1
            else:
                losses += 1
                
            if balance > peak_balance:
                peak_balance = balance
                
            drawdown_dollars = peak_balance - balance
            drawdown_pct = (drawdown_dollars / peak_balance) * 100
            
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct
                max_drawdown_dollars = drawdown_dollars
                
            if balance <= 0:
                print(f"Risk {risk_pct}%: BLOWN ACCOUNT!")
                break
                
        if balance > 0:
            roi = ((balance - initial_balance) / initial_balance) * 100
            print(f"Risk {risk_pct}% per trade:")
            print(f"  Ending Balance: ${balance:,.2f} (ROI: {roi:+.2f}%)")
            print(f"  Max Drawdown:   ${max_drawdown_dollars:,.2f} ({max_drawdown_pct:.2f}%)")
            print(f"  Wins/Losses:    {wins}/{losses} (Win Rate: {(wins/(wins+losses))*100:.2f}%)")
            print(f"  Risk/Reward ratio at this risk makes it {'VERY SAFE' if max_drawdown_pct < 15 else 'MODERATE' if max_drawdown_pct < 30 else 'HIGH RISK' if max_drawdown_pct < 50 else 'DANGEROUS'}")
            print("-" * 50)

run_scaling_simulation()
