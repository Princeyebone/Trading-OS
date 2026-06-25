import sys
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import MetaTrader5 as mt5
import ta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=30)
    
    print(f"Fetching M5 data from {start_time.date()} to {now.date()}...")
    
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_time, now)
    
    if m5_rates is None or len(m5_rates) == 0:
        print("Failed to get data.")
        return
        
    df = pd.DataFrame(m5_rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df.set_index('time', inplace=True)
    
    # Strategy Indicators
    df['range'] = df['high'] - df['low']
    df['avg_range_20'] = df['range'].rolling(window=20).mean()
    df['sma_20'] = ta.trend.sma_indicator(df['close'], window=20)
    df['rsi_14'] = ta.momentum.rsi(df['close'], window=14)
    df['rsi_rising'] = df['rsi_14'] > df['rsi_14'].shift(1)
    
    df.dropna(inplace=True)
    
    EST = ZoneInfo("America/New_York")
    
    total_pnl_pips = 0.0
    wins = 0
    losses = 0
    time_stops = 0
    
    print("\n" + "="*90)
    print(f"{'Entry Time':<20} | {'Entry':<8} | {'SL':<8} | {'TP':<8} | {'PnL (pips)':<12} | {'Result'}")
    print("="*90)

    in_trade = False
    trade_entry_price = 0.0
    trade_entry_time = None
    trade_sl = 0.0
    trade_tp = 0.0
    candles_in_trade = 0
    
    # Buy Stop logic
    pending_buy_stop = False
    bs_price = 0.0
    bs_sl = 0.0
    bs_tp = 0.0
    bs_candles_waiting = 0
    
    for current_time, row in df.iterrows():
        est_time = current_time.astimezone(EST)
        h = row['high']
        l = row['low']
        c = row['close']
        o = row['open']
        
        if in_trade:
            candles_in_trade += 1
            
            # Check TP / SL hit
            hit_sl = l <= trade_sl
            hit_tp = h >= trade_tp
            
            if hit_sl and hit_tp:
                # Whipsaw candle, assume SL hit first to be conservative
                hit_tp = False
                
            if hit_sl:
                pnl = (trade_sl - trade_entry_price) * 10.0
                total_pnl_pips += pnl
                losses += 1
                in_trade = False
                print(f"{trade_entry_time.strftime('%m-%d %H:%M'):<20} | {trade_entry_price:<8.2f} | {trade_sl:<8.2f} | {trade_tp:<8.2f} | {pnl:<12.1f} | LOSS")
                continue
                
            if hit_tp:
                pnl = (trade_tp - trade_entry_price) * 10.0
                total_pnl_pips += pnl
                wins += 1
                in_trade = False
                print(f"{trade_entry_time.strftime('%m-%d %H:%M'):<20} | {trade_entry_price:<8.2f} | {trade_sl:<8.2f} | {trade_tp:<8.2f} | {pnl:<12.1f} | WIN")
                continue
                
            # Time stop: 30 minutes = 6 M5 candles
            if candles_in_trade >= 6:
                pnl = (c - trade_entry_price) * 10.0
                total_pnl_pips += pnl
                if pnl > 0: wins += 1
                else: losses += 1
                time_stops += 1
                in_trade = False
                res = "TIME_WIN" if pnl > 0 else "TIME_LOSS"
                print(f"{trade_entry_time.strftime('%m-%d %H:%M'):<20} | {trade_entry_price:<8.2f} | {trade_sl:<8.2f} | {trade_tp:<8.2f} | {pnl:<12.1f} | {res}")
                continue
            
            continue

        if pending_buy_stop:
            # Check if triggered
            if h >= bs_price:
                in_trade = True
                trade_entry_price = bs_price
                trade_entry_time = current_time
                trade_sl = bs_sl
                trade_tp = bs_tp
                candles_in_trade = 0
                pending_buy_stop = False
                # Re-evaluate this candle for SL/TP since we just entered
                # (simplified: we ignore intra-candle execution details and wait for next candle to process management)
            else:
                bs_candles_waiting += 1
                if bs_candles_waiting >= 3: # Cancel if not triggered in 15 mins
                    pending_buy_stop = False

        # Session filter: 8 AM to 12 PM EST
        if not (8 <= est_time.hour < 12):
            continue
            
        if pending_buy_stop or in_trade:
            continue

        # ENTRY TRIGGER
        # 1. Bullish candle
        is_bullish = c > o
        # 2. Range >= 1.5 * avg_range_20
        is_big = row['range'] >= (1.5 * row['avg_range_20'])
        # 3. Close > 20 SMA
        above_sma = c > row['sma_20']
        # 4. RSI > 60 and rising
        rsi_valid = row['rsi_14'] > 60 and row['rsi_rising']
        
        if is_bullish and is_big and above_sma and rsi_valid:
            # Place buy stop
            pending_buy_stop = True
            bs_price = h + 0.1 # Entry at High
            bs_sl = l - 0.1 # SL at Low
            risk = bs_price - bs_sl
            bs_tp = bs_price + (2.0 * risk) # 2R TP
            bs_candles_waiting = 0

    print("="*90)
    print(f"M5 2R CANDLE-BREAK SIMULATION | Last 30 Days")
    print(f"Total Trades: {wins + losses}")
    print(f"Wins: {wins} | Losses: {losses} | Time Stops: {time_stops}")
    print(f"Win Rate: {(wins/(wins+losses)*100) if (wins+losses)>0 else 0:.1f}%")
    print(f"Net PnL: {total_pnl_pips:+.1f} pips")
    print("="*90)

if __name__ == "__main__":
    run()
