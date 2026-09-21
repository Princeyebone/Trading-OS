import sys
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")
sys.path.append("c:/Users/HP/OneDrive/Desktop/tb/backend")

from engine.pattern_detector import detect_inversion_fair_value_gaps

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

time_from_data = datetime.now() - timedelta(days=3)
time_to_data = datetime.now() + timedelta(days=1)
rates_m5 = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, time_from_data, time_to_data)
df_m5 = pd.DataFrame(rates_m5)
df_m5['time_dt'] = pd.to_datetime(df_m5['time'], unit='s')
df_m5.set_index('time_dt', inplace=True)

def simulate_trade(entry_time_ts, entry_price, direction, volume, orig_exit_time_ts, actual_profit, out_deal):
    # This just returns the control simulation (exact match) since we are testing ENTRY filters
    return actual_profit

results = {
    "Control (Real Trades)": {"pnl": 0.0, "wins": 0, "losses": 0, "skipped": 0},
    "Opt6 (IFVG Filtered)": {"pnl": 0.0, "wins": 0, "losses": 0, "skipped": 0, "saved_losses": 0, "killed_wins": 0}
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
    
    # Check Control
    results["Control (Real Trades)"]["pnl"] += actual_profit
    if actual_profit > 0:
        results["Control (Real Trades)"]["wins"] += 1
    else:
        results["Control (Real Trades)"]["losses"] += 1

    # Opt6: IFVG Filter
    entry_dt = pd.to_datetime(in_deal.time, unit='s')
    # Get M5 data up to entry time
    m5_slice = df_m5.loc[:entry_dt].copy()
    
    blocked = False
    
    if len(m5_slice) >= 20:
        ifvgs = detect_inversion_fair_value_gaps(m5_slice)
        for ifvg in ifvgs:
            bars_ago = (len(m5_slice) - 1) - ifvg["bar_index"]
            if bars_ago > 24: # Must be somewhat recent (2 hours)
                continue
                
            gap_dir = ifvg["direction"]
            gap_high = ifvg["high"]
            gap_low = ifvg["low"]
            
            # IFVG rules for filtering XAGI1
            if direction == "LONG" and gap_dir == "BEARISH":
                # We are trying to buy, but there is a Bearish IFVG (Resistance) above us
                # If the IFVG is within $2.00 (20 pips) above our entry price
                if entry_price < gap_low and (gap_low - entry_price) < 2.0:
                    blocked = True
                    break
                    
            elif direction == "SHORT" and gap_dir == "BULLISH":
                # We are trying to sell, but there is a Bullish IFVG (Support) below us
                if entry_price > gap_high and (entry_price - gap_high) < 2.0:
                    blocked = True
                    break
                    
    if blocked:
        results["Opt6 (IFVG Filtered)"]["skipped"] += 1
        if actual_profit < 0:
            results["Opt6 (IFVG Filtered)"]["saved_losses"] += 1
        else:
            results["Opt6 (IFVG Filtered)"]["killed_wins"] += 1
    else:
        results["Opt6 (IFVG Filtered)"]["pnl"] += actual_profit
        if actual_profit > 0:
            results["Opt6 (IFVG Filtered)"]["wins"] += 1
        else:
            results["Opt6 (IFVG Filtered)"]["losses"] += 1

print("\n--- SIMULATION RESULTS (68 Trades) ---")
for name, data in results.items():
    total = data['wins'] + data['losses']
    wr = (data['wins'] / total * 100) if total > 0 else 0
    print(f"{name: <25} | Executed: {total} (Skipped {data['skipped']}) | Win Rate: {wr:.1f}% | Net PnL: ${data['pnl']:.2f}")
    if "saved_losses" in data:
        print(f"  -> Saved Losses: {data['saved_losses']} | Killed Wins: {data['killed_wins']}")

mt5.shutdown()
