import pandas as pd
import MetaTrader5 as mt5

def run_fixed_lot_simulation():
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
    
    print("Extracting Scalper signals...")
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

    print("Running tick simulation to build trade sequence...")
    
    trades_executed = []
    active_trade = None
    pending_order = None
    signal_idx = 0
    signals = mom_signals
    
    trail = 30.0 # 30 pips
    
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
            
            if dir == "LONG":
                if c['high'] >= entry + 3.0:
                    trades_executed.append({"pips": 30.0})
                    active_trade = None
                    continue
                    
                if c['low'] <= sl:
                    if active_trade.get('locked', 0) > 0:
                        trades_executed.append({"pips": active_trade['locked']})
                    else:
                        trades_executed.append({"pips": (sl - entry) * 10})
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
                    trades_executed.append({"pips": 30.0})
                    active_trade = None
                    continue
                    
                if c['high'] >= sl:
                    if active_trade.get('locked', 0) > 0:
                        trades_executed.append({"pips": active_trade['locked']})
                    else:
                        trades_executed.append({"pips": (entry - sl) * 10})
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
    
    # Simulate FIXED lot sizes
    fixed_lots = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50]
    initial_balance = 500.0  # Assume $500 demo balance which corresponds to 0.01/0.02 lots
    
    print("\n--- FIXED LOT SIZE SIMULATION (Starting Balance: $500, roughly 2 Months of Trades) ---")
    
    for lots in fixed_lots:
        balance = initial_balance
        peak_balance = initial_balance
        max_drawdown_dollars = 0.0
        
        wins = 0
        losses = 0
        
        for t in trades_executed:
            # 1 standard lot = $10 per pip
            # So PnL = pips * lots * 10.0
            trade_pnl = t['pips'] * (lots * 10.0)
            
            balance += trade_pnl
            
            if trade_pnl > 0:
                wins += 1
            else:
                losses += 1
                
            if balance > peak_balance:
                peak_balance = balance
                
            drawdown_dollars = peak_balance - balance
            
            if drawdown_dollars > max_drawdown_dollars:
                max_drawdown_dollars = drawdown_dollars
                
            if balance <= 0:
                print(f"Fixed {lots} Lots: BLOWN ACCOUNT!")
                break
                
        if balance > 0:
            roi = ((balance - initial_balance) / initial_balance) * 100
            print(f"Fixed Lot Size: {lots} Lots per trade:")
            print(f"  Ending Balance: ${balance:,.2f} (Profit: +${(balance - initial_balance):,.2f})")
            print(f"  Max Drawdown:   ${max_drawdown_dollars:,.2f}")
            print(f"  Wins/Losses:    {wins}/{losses} (Win Rate: {(wins/(wins+losses))*100:.2f}%)")
            print("-" * 60)

run_fixed_lot_simulation()
