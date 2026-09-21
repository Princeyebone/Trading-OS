import sys
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

MAGIC_XAGI1 = 202600
SYMBOL = "XAUUSD"

# 1. Fetch exactly the OUT deals that happened in the last 24 hours
end_time = datetime.now() + timedelta(days=1)
start_time = datetime.now() - timedelta(hours=24)
recent_deals = mt5.history_deals_get(start_time, end_time)

if not recent_deals:
    print("No deals found.")
    sys.exit(0)

out_deals = [d for d in recent_deals if d.entry == 1 and d.magic == MAGIC_XAGI1 and d.symbol == SYMBOL]

# We need a large chunk of M1 and M15 data to simulate properly
time_from_m1 = datetime.now() - timedelta(days=3)
time_to_data = datetime.now() + timedelta(days=1)
rates_m1 = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, time_from_m1, time_to_data)

# Fetch 20 days of M15 to properly warm up the exponential MACD!
time_from_m15 = datetime.now() - timedelta(days=20)
rates_m15 = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M15, time_from_m15, time_to_data)

df_m1 = pd.DataFrame(rates_m1)
df_m1['time'] = pd.to_datetime(df_m1['time'], unit='s')
df_m1.set_index('time', inplace=True)

df_m15 = pd.DataFrame(rates_m15)
df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')
df_m15.set_index('time', inplace=True)

# Calculate M15 MACD
ema12 = df_m15['close'].ewm(span=12, adjust=False).mean()
ema26 = df_m15['close'].ewm(span=26, adjust=False).mean()
df_m15['macd'] = ema12 - ema26

def simulate_trade(entry_time_ts, entry_price, direction, volume, orig_exit_time_ts, config):
    start_lock_pips = config['start_lock']
    step_gain_pips = config['step_gain']
    step_lock_pips = config['step_lock']
    use_m15_macd = config['use_m15']
    
    # We simulate from entry_time to NOW
    entry_dt = pd.to_datetime(entry_time_ts, unit='s')
    now_dt = pd.to_datetime(datetime.now(timezone.utc).timestamp(), unit='s')
    
    trade_m1 = df_m1.loc[entry_dt:]
    
    highest_profit_pips = 0.0
    locked_profit_pips = 0.0
    
    # 1 pip on Gold = $0.1 per oz. Since MT5 'point' is 0.01, pip_multiplier = 10
    pip_multiplier = 10.0
    
    for current_time, row in trade_m1.iterrows():
        # High/Low logic to find max excursion within the minute
        if direction == "LONG":
            max_price = row['high']
            min_price = row['low']
            close_price = row['close']
            
            highest_possible_profit_pips = (max_price - entry_price) * pip_multiplier
            if highest_possible_profit_pips > highest_profit_pips:
                highest_profit_pips = highest_possible_profit_pips
                
            # Dynamic TP Lock
            if highest_profit_pips >= start_lock_pips:
                steps = int((highest_profit_pips - start_lock_pips) // step_gain_pips)
                new_lock = start_lock_pips + (steps * step_lock_pips)
                if new_lock > locked_profit_pips:
                    locked_profit_pips = new_lock
                    
            # Check if lowest drop hits the lock
            current_min_profit = (min_price - entry_price) * pip_multiplier
            if locked_profit_pips > 0 and current_min_profit <= locked_profit_pips:
                # Stopped out in profit by ratchet
                exit_price = entry_price + (locked_profit_pips / pip_multiplier)
                return exit_price, "TP_LOCK"
                
        else: # SHORT
            max_price = row['low'] # for short, low is best
            min_price = row['high'] # for short, high is worst
            close_price = row['close']
            
            highest_possible_profit_pips = (entry_price - max_price) * pip_multiplier
            if highest_possible_profit_pips > highest_profit_pips:
                highest_profit_pips = highest_possible_profit_pips
                
            # Dynamic TP Lock
            if highest_profit_pips >= start_lock_pips:
                steps = int((highest_profit_pips - start_lock_pips) // step_gain_pips)
                new_lock = start_lock_pips + (steps * step_lock_pips)
                if new_lock > locked_profit_pips:
                    locked_profit_pips = new_lock
                    
            # Check if lowest drop hits the lock
            current_min_profit = (entry_price - min_price) * pip_multiplier
            if locked_profit_pips > 0 and current_min_profit <= locked_profit_pips:
                # Stopped out in profit by ratchet
                exit_price = entry_price - (locked_profit_pips / pip_multiplier)
                return exit_price, "TP_LOCK"
                
        # At the end of every minute, check if the M15 candle closed and MACD crossed
        if use_m15_macd and current_time.minute % 15 == 0: # M15 candle closed
            # Get MACD of this closed M15 candle and previous one
            try:
                # Find the M15 candle that corresponds to this exact time
                # It is the candle that just closed
                idx = df_m15.index.get_indexer([current_time], method='pad')[0]
                macd_curr = df_m15['macd'].iloc[idx]
                macd_prev = df_m15['macd'].iloc[idx-1]
                
                # If LONG, cross below 0 is reversal
                if direction == "LONG" and macd_prev >= 0 and macd_curr < 0:
                    return close_price, "M15_REVERSAL"
                # If SHORT, cross above 0 is reversal
                if direction == "SHORT" and macd_prev <= 0 and macd_curr > 0:
                    return close_price, "M15_REVERSAL"
            except:
                pass
                
        # To keep simulation somewhat bounded to reality for Control, 
        # if the trade reached its exact original exit time, we close it manually (assuming H1 MACD or similar closed it)
        # But ONLY if we aren't testing 'Letting Winners Run' indefinitely. 
        # Actually, since Option 1 and Option 3 change the nature of the trade, they might stay open.
        # But we must simulate the original exit if neither TP nor M15 MACD hit.
        if current_time.timestamp() >= orig_exit_time_ts:
            return 0.0, "ORIGINAL_EXIT"
            
    # Still open at the end of data
    return trade_m1['close'].iloc[-1], "STILL_OPEN"


results = {
    "Control (Real Trades)": {"pnl": 0.0, "wins": 0, "losses": 0},
    "Opt1 (Lock 40 pips)": {"pnl": 0.0, "wins": 0, "losses": 0},
    "Opt3 (M15 MACD)": {"pnl": 0.0, "wins": 0, "losses": 0},
    "Opt1 + Opt3": {"pnl": 0.0, "wins": 0, "losses": 0}
}

configs = {
    "Control (Real Trades)": {'start_lock': 20.0, 'step_gain': 10.0, 'step_lock': 10.0, 'use_m15': False},
    "Opt1 (Lock 40 pips)": {'start_lock': 40.0, 'step_gain': 10.0, 'step_lock': 10.0, 'use_m15': False},
    "Opt3 (M15 MACD)": {'start_lock': 20.0, 'step_gain': 10.0, 'step_lock': 10.0, 'use_m15': True},
    "Opt1 + Opt3": {'start_lock': 40.0, 'step_gain': 10.0, 'step_lock': 10.0, 'use_m15': True}
}

for out_deal in out_deals:
    pos_id = out_deal.position_id
    pos_deals = mt5.history_deals_get(position=pos_id)
    if not pos_deals: continue
    in_deal = next((d for d in pos_deals if d.entry == 0), None)
    if not in_deal: continue
        
    actual_profit = out_deal.profit + out_deal.commission + out_deal.swap
    direction = "LONG" if in_deal.type == mt5.DEAL_TYPE_BUY else "SHORT"
    entry_price = in_deal.price
    volume = in_deal.volume
    oz = volume * 100.0
    
    for name, conf in configs.items():
        exit_price, reason = simulate_trade(in_deal.time, entry_price, direction, volume, out_deal.time, conf)
        
        if reason == "ORIGINAL_EXIT":
            sim_pnl = actual_profit # Perfect match for control
        else:
            # Calculate simulated PnL and apply commission/swap
            if direction == "LONG":
                gross = (exit_price - entry_price) * oz
            else:
                gross = (entry_price - exit_price) * oz
                
            # Assume 1.5 pips of slippage on simulated stops/limits + real commission
            slippage_cost = 1.5 * 0.1 * oz
            sim_pnl = gross - slippage_cost + out_deal.commission + out_deal.swap
            
        results[name]["pnl"] += sim_pnl
        if sim_pnl > 0:
            results[name]["wins"] += 1
        else:
            results[name]["losses"] += 1

print("\n--- SIMULATION RESULTS (68 Trades) ---")
for name, data in results.items():
    total = data['wins'] + data['losses']
    wr = (data['wins'] / total * 100) if total > 0 else 0
    print(f"{name: <16} | Win Rate: {wr:.1f}% | Net PnL: ${data['pnl']:.2f}")

mt5.shutdown()
