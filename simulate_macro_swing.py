import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    # Fetch last 6 months of H4 data
    start_time = now - timedelta(days=180)
    
    print(f"Fetching data from {start_time.date()} to {now.date()}...")
    
    h4_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H4, start_time, now)
    d1_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_D1, start_time - timedelta(days=100), now)
    
    if h4_rates is None or d1_rates is None or len(h4_rates) == 0 or len(d1_rates) == 0:
        print("Failed to get data.")
        return
        
    h4_df = pd.DataFrame(h4_rates)
    d1_df = pd.DataFrame(d1_rates)
    
    h4_df['time'] = pd.to_datetime(h4_df['time'], unit='s', utc=True)
    d1_df['time'] = pd.to_datetime(d1_df['time'], unit='s', utc=True)
    
    # Calculate Daily trend
    d1_df['ema50'] = ta.trend.ema_indicator(d1_df['close'], window=50)
    
    # Calculate H4 trend & structure
    h4_df['ema20'] = ta.trend.ema_indicator(h4_df['close'], window=20)
    h4_df['ema50'] = ta.trend.ema_indicator(h4_df['close'], window=50)
    
    # Simulate forward
    SL_DIST = 10.0  # 100 pips (10.0 points in XAUUSD)
    TP_DIST = 30.0  # 300 pips (30.0 points, 1:3 R:R)
    
    total_pnl_pips = 0.0
    wins = 0
    losses = 0
    
    print("\n" + "="*80)
    print(f"{'Entry Time':<20} | {'Entry':<10} | {'PnL (pips)':<12} | {'Result'}")
    print("="*80)

    # To avoid taking 50 trades in the same trend, we track if we are already in a trade
    in_trade = False
    trade_entry_price = 0.0
    trade_entry_time = None
    
    for i in range(50, len(h4_df)):
        curr_h4 = h4_df.iloc[i]
        prev_h4 = h4_df.iloc[i-1]
        
        curr_ts = curr_h4['time']
        
        if in_trade:
            # Check if trade hit SL or TP
            # For H4, we look at the High/Low of the current candle
            h = curr_h4['high']
            l = curr_h4['low']
            
            # Simple simulation: check low first (conservative)
            if l <= trade_entry_price - SL_DIST:
                pnl = -SL_DIST * 10
                total_pnl_pips += pnl
                losses += 1
                in_trade = False
                print(f"{trade_entry_time.strftime('%Y-%m-%d %H:%M'):<20} | {trade_entry_price:<10.2f} | {pnl:<12.1f} | LOSS")
            elif h >= trade_entry_price + TP_DIST:
                pnl = TP_DIST * 10
                total_pnl_pips += pnl
                wins += 1
                in_trade = False
                print(f"{trade_entry_time.strftime('%Y-%m-%d %H:%M'):<20} | {trade_entry_price:<10.2f} | {pnl:<12.1f} | WIN")
                
            continue

        # Look up Daily trend at this time
        past_d1 = d1_df[d1_df['time'] <= curr_ts]
        if len(past_d1) == 0: continue
        daily_close = past_d1.iloc[-1]['close']
        daily_ema50 = past_d1.iloc[-1]['ema50']
        
        # Strategy: LONG ONLY
        # Condition 1: Daily is strictly Bullish (Price > D1 EMA 50)
        daily_bullish = daily_close > daily_ema50
        
        # Condition 2: H4 pullback and Breakout
        # H4 was below EMA 20, but just closed above it (momentum shifting up)
        h4_breakout = prev_h4['close'] < prev_h4['ema20'] and curr_h4['close'] > curr_h4['ema20']
        
        # Condition 3: H4 EMA 20 is above H4 EMA 50 (H4 Trend is up)
        h4_trend_up = curr_h4['ema20'] > curr_h4['ema50']
        
        if daily_bullish and h4_breakout and h4_trend_up:
            in_trade = True
            trade_entry_price = curr_h4['close']
            trade_entry_time = curr_ts

    print("="*80)
    print(f"MACRO SWING SIMULATION (LONG ONLY, 1:3 R/R) | Last 6 Months")
    print(f"Total Trades: {wins + losses}")
    print(f"Wins: {wins} | Losses: {losses} | Win Rate: {(wins/(wins+losses)*100) if (wins+losses)>0 else 0:.1f}%")
    print(f"Net PnL: {total_pnl_pips:+.1f} pips")
    print("="*80)

if __name__ == "__main__":
    run()
