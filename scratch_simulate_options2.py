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

# Fetch exactly the OUT deals that happened in the last 24 hours
end_time = datetime.now() + timedelta(days=1)
start_time = datetime.now() - timedelta(hours=24)
recent_deals = mt5.history_deals_get(start_time, end_time)

if not recent_deals:
    print("No deals found.")
    sys.exit(0)

out_deals = [d for d in recent_deals if d.entry == 1 and d.magic == MAGIC_XAGI1 and d.symbol == SYMBOL]

time_from_m1 = datetime.now() - timedelta(days=3)
time_to_data = datetime.now() + timedelta(days=1)
rates_m1 = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, time_from_m1, time_to_data)

df_m1 = pd.DataFrame(rates_m1)
df_m1['time'] = pd.to_datetime(df_m1['time'], unit='s')
df_m1.set_index('time', inplace=True)

def simulate_trade(entry_time_ts, entry_price, direction, volume, orig_exit_time_ts, config):
    start_lock_pips = config.get('start_lock', 20.0)
    step_gain_pips = config.get('step_gain', 10.0)
    step_lock_pips = config.get('step_lock', 10.0)
    smooth_trail = config.get('smooth_trail', False)
    trail_dist = config.get('trail_dist', 10.0)
    
    entry_dt = pd.to_datetime(entry_time_ts, unit='s')
    now_dt = pd.to_datetime(datetime.now(timezone.utc).timestamp(), unit='s')
    trade_m1 = df_m1.loc[entry_dt:]
    
    highest_profit_pips = 0.0
    locked_profit_pips = 0.0
    pip_multiplier = 10.0
    
    for current_time, row in trade_m1.iterrows():
        if direction == "LONG":
            max_price = row['high']
            min_price = row['low']
            close_price = row['close']
            
            highest_possible_profit_pips = (max_price - entry_price) * pip_multiplier
            if highest_possible_profit_pips > highest_profit_pips:
                highest_profit_pips = highest_possible_profit_pips
                
            # Dynamic TP Lock
            if highest_profit_pips >= start_lock_pips:
                if smooth_trail:
                    new_lock = highest_profit_pips - trail_dist
                else:
                    steps = int((highest_profit_pips - start_lock_pips) // step_gain_pips)
                    new_lock = start_lock_pips + (steps * step_lock_pips)
                    
                if new_lock > locked_profit_pips:
                    locked_profit_pips = new_lock
                    
            # Check if hit lock
            current_min_profit = (min_price - entry_price) * pip_multiplier
            if locked_profit_pips > 0 and current_min_profit <= locked_profit_pips:
                exit_price = entry_price + (locked_profit_pips / pip_multiplier)
                return exit_price, "TP_LOCK"
                
        else: # SHORT
            max_price = row['low']
            min_price = row['high']
            close_price = row['close']
            
            highest_possible_profit_pips = (entry_price - max_price) * pip_multiplier
            if highest_possible_profit_pips > highest_profit_pips:
                highest_profit_pips = highest_possible_profit_pips
                
            # Dynamic TP Lock
            if highest_profit_pips >= start_lock_pips:
                if smooth_trail:
                    new_lock = highest_profit_pips - trail_dist
                else:
                    steps = int((highest_profit_pips - start_lock_pips) // step_gain_pips)
                    new_lock = start_lock_pips + (steps * step_lock_pips)
                    
                if new_lock > locked_profit_pips:
                    locked_profit_pips = new_lock
                    
            # Check if hit lock
            current_min_profit = (entry_price - min_price) * pip_multiplier
            if locked_profit_pips > 0 and current_min_profit <= locked_profit_pips:
                exit_price = entry_price - (locked_profit_pips / pip_multiplier)
                return exit_price, "TP_LOCK"
                
        if current_time.timestamp() >= orig_exit_time_ts:
            return 0.0, "ORIGINAL_EXIT"
            
    return trade_m1['close'].iloc[-1], "STILL_OPEN"


results = {
    "Control (Real Trades)": {"pnl": 0.0, "wins": 0, "losses": 0},
    "Opt4 (Smooth Trailing)": {"pnl": 0.0, "wins": 0, "losses": 0},
    "Opt5 (Exclude NY Volatility)": {"pnl": 0.0, "wins": 0, "losses": 0, "skipped": 0}
}

configs = {
    "Control (Real Trades)": {'start_lock': 20.0, 'step_gain': 10.0, 'step_lock': 10.0, 'smooth_trail': False},
    "Opt4 (Smooth Trailing)": {'start_lock': 20.0, 'smooth_trail': True, 'trail_dist': 10.0},
    "Opt5 (Exclude NY Volatility)": {'start_lock': 20.0, 'step_gain': 10.0, 'step_lock': 10.0, 'smooth_trail': False, 'exclude_hours': (12, 16)}
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
    
    in_dt = datetime.fromtimestamp(in_deal.time, timezone.utc)
    in_hour = in_dt.hour
    
    for name, conf in configs.items():
        if 'exclude_hours' in conf:
            start_h, end_h = conf['exclude_hours']
            if start_h <= in_hour <= end_h:
                results[name]["skipped"] += 1
                continue
                
        exit_price, reason = simulate_trade(in_deal.time, entry_price, direction, volume, out_deal.time, conf)
        
        if reason == "ORIGINAL_EXIT":
            sim_pnl = actual_profit
        else:
            if direction == "LONG":
                gross = (exit_price - entry_price) * oz
            else:
                gross = (entry_price - exit_price) * oz
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
    if name == "Opt5 (Exclude NY Volatility)":
        print(f"{name: <28} | Trades: {total} (Skipped {data['skipped']}) | Win Rate: {wr:.1f}% | Net PnL: ${data['pnl']:.2f}")
    else:
        print(f"{name: <28} | Trades: {total} | Win Rate: {wr:.1f}% | Net PnL: ${data['pnl']:.2f}")

mt5.shutdown()
