import pandas as pd
import ta
import MetaTrader5 as mt5
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.pattern_detector import detect_order_blocks

def run_simulation():
    if not mt5.initialize():
        return

    symbol = "XAUUSD"
    timeframe = mt5.TIMEFRAME_M15
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 15000)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['ema200'] = ta.trend.ema_indicator(df['close'], window=200)
    
    total_trades = 0
    wins = 0
    losses = 0
    total_pips = 0.0
    
    active_trade = None
    pending_order = None
    
    for i in range(200, len(df)):
        current_c = df.iloc[i]
        
        # 1. Manage Active Trade
        if active_trade:
            dir = active_trade['direction']
            entry = active_trade['entry']
            
            if dir == "LONG":
                profit_pips = (current_c['high'] - entry) * 10
                if profit_pips > active_trade['highest_profit']:
                    active_trade['highest_profit'] = profit_pips
                if active_trade['highest_profit'] >= 30.0:
                    new_locked = active_trade['highest_profit'] - 30.0
                    if new_locked > active_trade['locked']:
                        active_trade['locked'] = new_locked
                        active_trade['sl'] = entry + (active_trade['locked'] / 10.0)
                if current_c['low'] <= active_trade['sl']:
                    total_trades += 1
                    final_pips = (active_trade['sl'] - entry) * 10
                    total_pips += final_pips
                    if final_pips > 0: wins += 1
                    else: losses += 1
                    active_trade = None
                    continue
            elif dir == "SHORT":
                profit_pips = (entry - current_c['low']) * 10
                if profit_pips > active_trade['highest_profit']:
                    active_trade['highest_profit'] = profit_pips
                if active_trade['highest_profit'] >= 30.0:
                    new_locked = active_trade['highest_profit'] - 30.0
                    if new_locked > active_trade['locked']:
                        active_trade['locked'] = new_locked
                        active_trade['sl'] = entry - (active_trade['locked'] / 10.0)
                if current_c['high'] >= active_trade['sl']:
                    total_trades += 1
                    final_pips = (entry - active_trade['sl']) * 10
                    total_pips += final_pips
                    if final_pips > 0: wins += 1
                    else: losses += 1
                    active_trade = None
                    continue
                    
        # 2. Check Pending Order
        if pending_order and not active_trade:
            if pending_order['direction'] == "LONG" and current_c['low'] <= pending_order['entry']:
                active_trade = pending_order.copy()
                pending_order = None
                # Check immediate stop loss
                if current_c['low'] <= active_trade['sl']:
                    total_trades += 1
                    final_pips = (active_trade['sl'] - active_trade['entry']) * 10
                    total_pips += final_pips
                    losses += 1
                    active_trade = None
            elif pending_order['direction'] == "SHORT" and current_c['high'] >= pending_order['entry']:
                active_trade = pending_order.copy()
                pending_order = None
                if current_c['high'] >= active_trade['sl']:
                    total_trades += 1
                    final_pips = (active_trade['entry'] - active_trade['sl']) * 10
                    total_pips += final_pips
                    losses += 1
                    active_trade = None
                    
        # 3. Scan for new setups every candle
        if not active_trade:
            is_bullish = current_c['close'] > current_c['ema200']
            target_dir = 'BULLISH' if is_bullish else 'BEARISH'
            window_df = df.iloc[i-40:i].reset_index(drop=True)
            df_filter = "long" if is_bullish else "short"
            obs = detect_order_blocks(window_df, direction=df_filter)
            valid_obs = [ob for ob in obs if ob['direction'] == target_dir]
            
            if valid_obs:
                ob = valid_obs[0]
                limit_price = ob['high'] if is_bullish else ob['low']
                sl_dist_pips = (ob['high'] - ob['low']) * 10 + 10.0
                sl_dist_pips = max(15.0, min(50.0, sl_dist_pips))
                sl_price = limit_price - (sl_dist_pips / 10.0) if is_bullish else limit_price + (sl_dist_pips / 10.0)
                
                pending_order = {
                    'direction': "LONG" if is_bullish else "SHORT",
                    'entry': limit_price,
                    'sl': sl_price,
                    'highest_profit': 0.0,
                    'locked': 0.0
                }

    print(f"--- M15 SMC Order Block (30-pip Trail) Backtest ---")
    print(f"Total Setups Triggered: {total_trades}")
    print(f"Wins (Locked Profit): {wins}")
    print(f"Losses (Hit initial SL or 0 lock): {losses}")
    if total_trades > 0:
        print(f"Win Rate: {(wins/total_trades)*100:.2f}%")
        print(f"Total Pips Gained/Lost: {total_pips:.1f}")
        print(f"Average Pips Per Trade: {total_pips/total_trades:.1f}")

run_simulation()
