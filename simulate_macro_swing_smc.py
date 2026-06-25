import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta
import os

# Add parent directory to path so we can import engine modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.pattern_detector import detect_order_blocks

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
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
    d1_df['ema50'] = ta.trend.ema_indicator(d1_df['close'], window=50)
    
    total_pnl_pips = 0.0
    wins = 0
    losses = 0
    
    print("\n" + "="*90)
    print(f"{'Entry Time':<20} | {'Type':<6} | {'Entry':<8} | {'SL':<8} | {'PnL (pips)':<12} | {'Result'}")
    print("="*90)

    in_trade = False
    trade_entry_price = 0.0
    trade_sl = 0.0
    trade_tp = 0.0
    trade_entry_time = None
    
    active_ob = None
    
    for i in range(50, len(h4_df)):
        curr_h4 = h4_df.iloc[i]
        curr_ts = curr_h4['time']
        
        if in_trade:
            h = curr_h4['high']
            l = curr_h4['low']
            
            if l <= trade_sl:
                pnl = -(trade_entry_price - trade_sl) * 10
                total_pnl_pips += pnl
                losses += 1
                in_trade = False
                active_ob = None
                print(f"{curr_ts.strftime('%Y-%m-%d %H:%M'):<20} | {'LONG':<6} | {trade_entry_price:<8.2f} | {trade_sl:<8.2f} | {pnl:<12.1f} | LOSS")
            elif h >= trade_tp:
                pnl = (trade_tp - trade_entry_price) * 10
                total_pnl_pips += pnl
                wins += 1
                in_trade = False
                active_ob = None
                print(f"{curr_ts.strftime('%Y-%m-%d %H:%M'):<20} | {'LONG':<6} | {trade_entry_price:<8.2f} | {trade_sl:<8.2f} | {pnl:<12.1f} | WIN")
            continue

        past_d1 = d1_df[d1_df['time'] <= curr_ts]
        if len(past_d1) == 0: continue
        daily_close = past_d1.iloc[-1]['close']
        daily_ema50 = past_d1.iloc[-1]['ema50']
        
        if daily_close < daily_ema50:
            active_ob = None
            continue

        window_df = h4_df.iloc[i-40:i].reset_index(drop=True)
        obs = detect_order_blocks(window_df, direction="long")
        
        bullish_obs = [ob for ob in obs if ob['direction'] == 'BULLISH']
        if bullish_obs:
            latest_ob = bullish_obs[0]
            if active_ob is None or latest_ob['timestamp'] != active_ob['timestamp']:
                active_ob = latest_ob
                
        if active_ob:
            ob_high = active_ob['high']
            ob_low = active_ob['low']
            
            # Entry condition: Price pulls back into the OB zone
            # We must ensure the current candle is opening above and testing it, or just touching it
            if curr_h4['low'] <= ob_high and curr_h4['high'] >= ob_high:
                # Assume limit order fills at ob_high
                in_trade = True
                trade_entry_price = ob_high
                
                # SL = Buffer below the OB low
                sl_dist_pips = (ob_high - ob_low) * 10 + 20.0 
                sl_dist_pips = max(50.0, min(150.0, sl_dist_pips))
                
                trade_sl = trade_entry_price - (sl_dist_pips / 10.0)
                tp_dist_pips = sl_dist_pips * 3.0
                trade_tp = trade_entry_price + (tp_dist_pips / 10.0)
                trade_entry_time = curr_ts

    print("="*90)
    print(f"SMC MACRO SWING SIM (LONG ONLY, 1:3 R/R) | Last 6 Months")
    print(f"Total Trades: {wins + losses}")
    print(f"Wins: {wins} | Losses: {losses} | Win Rate: {(wins/(wins+losses)*100) if (wins+losses)>0 else 0:.1f}%")
    print(f"Net PnL: {total_pnl_pips:+.1f} pips")
    print("="*90)

if __name__ == "__main__":
    run()
