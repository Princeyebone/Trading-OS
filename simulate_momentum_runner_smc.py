import sys
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.pattern_detector import detect_order_blocks

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=30)
    
    print(f"Fetching M15 data from {start_time.date()} to {now.date()}...")
    
    m15_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M15, start_time, now)
    h1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start_time - timedelta(days=10), now)
    
    if m15_rates is None or h1_rates is None or len(m15_rates) == 0:
        print("Failed to get data.")
        return
        
    m15_df = pd.DataFrame(m15_rates)
    h1_df = pd.DataFrame(h1_rates)
    
    m15_df['time'] = pd.to_datetime(m15_df['time'], unit='s', utc=True)
    h1_df['time'] = pd.to_datetime(h1_df['time'], unit='s', utc=True)
    h1_df['ema50'] = ta.trend.ema_indicator(h1_df['close'], window=50)
    
    total_pnl_pips = 0.0
    wins = 0
    losses = 0
    
    print("\n" + "="*90)
    print(f"{'Entry Time':<20} | {'Type':<6} | {'Entry':<8} | {'Max Exc.':<10} | {'PnL (pips)':<12} | {'Result'}")
    print("="*90)

    in_trade = False
    trade_dir = ""
    trade_entry_price = 0.0
    trade_entry_time = None
    trade_sl = 0.0
    highest_profit = 0.0
    
    TRAILING_DISTANCE = 30.0 # 30 pips trailing stop to catch the full move
    
    active_ob = None
    
    for i in range(50, len(m15_df)):
        curr_m15 = m15_df.iloc[i]
        curr_ts = curr_m15['time']
        
        if in_trade:
            h = curr_m15['high']
            l = curr_m15['low']
            
            if trade_dir == "LONG":
                current_sl_price = trade_entry_price + ((highest_profit - TRAILING_DISTANCE) / 10.0)
                actual_sl_price = max(current_sl_price, trade_sl)
                
                if l <= actual_sl_price:
                    pnl = (actual_sl_price - trade_entry_price) * 10.0
                    total_pnl_pips += pnl
                    if pnl > 0: wins += 1
                    else: losses += 1
                    in_trade = False
                    active_ob = None
                    res = "WIN" if pnl > 0 else "LOSS"
                    print(f"{trade_entry_time.strftime('%m-%d %H:%M'):<20} | {trade_dir:<6} | {trade_entry_price:<8.2f} | {highest_profit:<10.1f} | {pnl:<12.1f} | {res}")
                    continue
                
                curr_high_profit = (h - trade_entry_price) * 10.0
                if curr_high_profit > highest_profit:
                    highest_profit = curr_high_profit
                    
            elif trade_dir == "SHORT":
                current_sl_price = trade_entry_price - ((highest_profit - TRAILING_DISTANCE) / 10.0)
                actual_sl_price = min(current_sl_price, trade_sl)
                
                if h >= actual_sl_price:
                    pnl = (trade_entry_price - actual_sl_price) * 10.0
                    total_pnl_pips += pnl
                    if pnl > 0: wins += 1
                    else: losses += 1
                    in_trade = False
                    active_ob = None
                    res = "WIN" if pnl > 0 else "LOSS"
                    print(f"{trade_entry_time.strftime('%m-%d %H:%M'):<20} | {trade_dir:<6} | {trade_entry_price:<8.2f} | {highest_profit:<10.1f} | {pnl:<12.1f} | {res}")
                    continue
                    
                curr_high_profit = (trade_entry_price - l) * 10.0
                if curr_high_profit > highest_profit:
                    highest_profit = curr_high_profit
                    
            continue

        past_h1 = h1_df[h1_df['time'] <= curr_ts]
        if len(past_h1) == 0: continue
        h1_close = past_h1.iloc[-1]['close']
        h1_ema50 = past_h1.iloc[-1]['ema50']
        
        # Scan for M15 Order Blocks
        window_df = m15_df.iloc[i-40:i].reset_index(drop=True)
        
        if h1_close > h1_ema50:
            obs = detect_order_blocks(window_df, direction="long")
            valid_obs = [ob for ob in obs if ob['direction'] == 'BULLISH']
            trade_dir_setup = "LONG"
        else:
            obs = detect_order_blocks(window_df, direction="short")
            valid_obs = [ob for ob in obs if ob['direction'] == 'BEARISH']
            trade_dir_setup = "SHORT"
            
        if valid_obs:
            latest_ob = valid_obs[0]
            if active_ob is None or latest_ob['timestamp'] != active_ob['timestamp']:
                active_ob = latest_ob
                
        if active_ob:
            ob_high = active_ob['high']
            ob_low = active_ob['low']
            
            if trade_dir_setup == "LONG":
                # Ensure price pulls back into the OB zone
                if curr_m15['low'] <= ob_high and curr_m15['high'] >= ob_high:
                    in_trade = True
                    trade_dir = "LONG"
                    trade_entry_price = ob_high
                    highest_profit = 0.0
                    
                    sl_dist_pips = (ob_high - ob_low) * 10 + 10.0 # buffer
                    sl_dist_pips = max(15.0, min(50.0, sl_dist_pips))
                    trade_sl = trade_entry_price - (sl_dist_pips / 10.0)
                    trade_entry_time = curr_ts
            else:
                if curr_m15['high'] >= ob_low and curr_m15['low'] <= ob_low:
                    in_trade = True
                    trade_dir = "SHORT"
                    trade_entry_price = ob_low
                    highest_profit = 0.0
                    
                    sl_dist_pips = (ob_high - ob_low) * 10 + 10.0 
                    sl_dist_pips = max(15.0, min(50.0, sl_dist_pips))
                    trade_sl = trade_entry_price + (sl_dist_pips / 10.0)
                    trade_entry_time = curr_ts

    print("="*90)
    print(f"M15 SMC MOMENTUM RUNNER SIM | Last 30 Days")
    print(f"Trailing Stop: {TRAILING_DISTANCE} pips")
    print(f"Total Trades: {wins + losses}")
    print(f"Wins: {wins} | Losses: {losses} | Win Rate: {(wins/(wins+losses)*100) if (wins+losses)>0 else 0:.1f}%")
    print(f"Net PnL: {total_pnl_pips:+.1f} pips")
    print("="*90)

if __name__ == "__main__":
    run()
