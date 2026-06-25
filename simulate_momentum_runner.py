import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    # Fetch last 30 days of M1 data to catch explosive intraday moves
    start_time = now - timedelta(days=30)
    
    print(f"Fetching M1 data from {start_time.date()} to {now.date()}...")
    
    m1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, start_time, now)
    
    if m1_rates is None or len(m1_rates) == 0:
        print("Failed to get data.")
        return
        
    df = pd.DataFrame(m1_rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df.set_index('time', inplace=True)
    
    # Calculate rolling volume and ATR for baseline
    df['vol_ma'] = df['tick_volume'].rolling(window=30).mean()
    df['body_size'] = abs(df['close'] - df['open']) * 10.0 # in pips
    df['body_ma'] = df['body_size'].rolling(window=30).mean()
    
    # Remove NaN
    df.dropna(inplace=True)
    
    total_pnl_pips = 0.0
    wins = 0
    losses = 0
    
    print("\n" + "="*90)
    print(f"{'Entry Time':<20} | {'Dir':<5} | {'Entry':<8} | {'Max Exc.':<10} | {'PnL (pips)':<12} | {'Result'}")
    print("="*90)

    in_trade = False
    trade_dir = ""
    trade_entry_price = 0.0
    trade_entry_time = None
    
    # Trailing Stop Settings
    # To catch big runs and balance out losses, we use a slightly wider trailing stop 
    # and don't aggressively lock Break-Even too early.
    INITIAL_SL_PIPS = 30.0
    TRAILING_DISTANCE = 30.0
    
    highest_profit = 0.0
    
    for current_time, row in df.iterrows():
        if in_trade:
            # Check for exits
            current_profit = 0.0
            h = row['high']
            l = row['low']
            
            if trade_dir == "LONG":
                # Did we hit SL during this minute?
                current_sl_price = trade_entry_price + ((highest_profit - TRAILING_DISTANCE) / 10.0)
                # Ensure SL never goes below initial SL
                initial_sl_price = trade_entry_price - (INITIAL_SL_PIPS / 10.0)
                actual_sl_price = max(current_sl_price, initial_sl_price)
                
                if l <= actual_sl_price:
                    # Stopped out
                    pnl = (actual_sl_price - trade_entry_price) * 10.0
                    total_pnl_pips += pnl
                    if pnl > 0: wins += 1
                    else: losses += 1
                    in_trade = False
                    res = "WIN" if pnl > 0 else "LOSS"
                    print(f"{trade_entry_time.strftime('%m-%d %H:%M'):<20} | {trade_dir:<5} | {trade_entry_price:<8.2f} | {highest_profit:<10.1f} | {pnl:<12.1f} | {res}")
                    continue
                
                # Update highest profit
                curr_high_profit = (h - trade_entry_price) * 10.0
                if curr_high_profit > highest_profit:
                    highest_profit = curr_high_profit
                    
            elif trade_dir == "SHORT":
                current_sl_price = trade_entry_price - ((highest_profit - TRAILING_DISTANCE) / 10.0)
                initial_sl_price = trade_entry_price + (INITIAL_SL_PIPS / 10.0)
                actual_sl_price = min(current_sl_price, initial_sl_price)
                
                if h >= actual_sl_price:
                    pnl = (trade_entry_price - actual_sl_price) * 10.0
                    total_pnl_pips += pnl
                    if pnl > 0: wins += 1
                    else: losses += 1
                    in_trade = False
                    res = "WIN" if pnl > 0 else "LOSS"
                    print(f"{trade_entry_time.strftime('%m-%d %H:%M'):<20} | {trade_dir:<5} | {trade_entry_price:<8.2f} | {highest_profit:<10.1f} | {pnl:<12.1f} | {res}")
                    continue
                    
                curr_high_profit = (trade_entry_price - l) * 10.0
                if curr_high_profit > highest_profit:
                    highest_profit = curr_high_profit
                    
            continue

        # ENTRY LOGIC: 
        # Looking for a pure momentum spike (explosive candle)
        # Condition 1: Volume is at least 3x the 30-minute average
        # Condition 2: The body size is at least 15 pips (massive 1-minute move)
        vol_spike = row['tick_volume'] > (row['vol_ma'] * 3.0)
        body_spike = row['body_size'] > 15.0
        
        if vol_spike and body_spike:
            in_trade = True
            trade_entry_price = row['close']
            trade_entry_time = current_time
            highest_profit = 0.0
            
            if row['close'] > row['open']:
                trade_dir = "LONG"
            else:
                trade_dir = "SHORT"

    print("="*90)
    print(f"MOMENTUM RUNNER SIMULATION (M1 Explosive Candles) | Last 30 Days")
    print(f"Trailing Stop: {TRAILING_DISTANCE} pips")
    print(f"Total Trades: {wins + losses}")
    print(f"Wins: {wins} | Losses: {losses} | Win Rate: {(wins/(wins+losses)*100) if (wins+losses)>0 else 0:.1f}%")
    print(f"Net PnL: {total_pnl_pips:+.1f} pips")
    print("="*90)

if __name__ == "__main__":
    run()
