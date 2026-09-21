import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timezone, timedelta

mt5.initialize()

def backtest_xau_hyper_scalper(start_dt, end_dt, name="Period"):
    print(f"\n=======================================================")
    print(f"  BACKTESTING XAU-i6 (Gold Hyper Scalper) - {name}")
    print(f"  From {start_dt} to {end_dt}")
    print(f"=======================================================")
    
    rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, start_dt, end_dt)
    if rates is None or len(rates) < 100:
        print("Not enough M1 rates available.")
        return None
        
    df = pd.DataFrame(rates)
    df['time_dt'] = pd.to_datetime(df['time'], unit='s', utc=True)
    
    # Indicators
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2.2)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    df['bb_mid'] = bb.bollinger_mavg()
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)
    
    trades = []
    in_trade = False
    trade_dir = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_time = None
    
    MIN_TARGET_POINTS = 1.20
    MAX_TARGET_POINTS = 4.00
    MAX_SL_POINTS = 3.50
    LOT_SIZE = 0.05
    
    for i in range(25, len(df)):
        c = df.iloc[i]
        
        # Check active trade exit
        if in_trade:
            # Check high/low of current candle
            hit_tp = False
            hit_sl = False
            
            if trade_dir == "LONG":
                if c['low'] <= sl_price:
                    hit_sl = True
                elif c['high'] >= tp_price:
                    hit_tp = True
            else: # SHORT
                if c['high'] >= sl_price:
                    hit_sl = True
                elif c['low'] <= tp_price:
                    hit_tp = True
                    
            if hit_tp or hit_sl:
                exit_price = tp_price if hit_tp else sl_price
                if hit_tp and hit_sl:
                    # Conservative assumption: hit SL first
                    exit_price = sl_price
                    outcome = "LOSS"
                else:
                    outcome = "WIN" if hit_tp else "LOSS"
                    
                points = (exit_price - entry_price) if trade_dir == "LONG" else (entry_price - exit_price)
                # On 0.05 lot of Gold, 1 point = $5.00
                pnl_dollars = points * 100.0 * LOT_SIZE
                
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': c['time_dt'],
                    'dir': trade_dir,
                    'entry': entry_price,
                    'exit': exit_price,
                    'points': round(points, 2),
                    'pnl': round(pnl_dollars, 2),
                    'outcome': outcome
                })
                in_trade = False
                continue
                
        # If not in trade, look for new signal on candle close of i-1
        prev_candle = df.iloc[i-1]
        p_close = prev_candle['close']
        p_lower = prev_candle['bb_lower']
        p_upper = prev_candle['bb_upper']
        p_mid = prev_candle['bb_mid']
        p_rsi = prev_candle['rsi']
        
        sig = None
        if p_close < p_lower and p_rsi < 35.0:
            sig = "LONG"
        elif p_close > p_upper and p_rsi > 65.0:
            sig = "SHORT"
            
        if sig:
            entry_price = c['open']
            target_pts = abs(entry_price - p_mid)
            target_pts = max(MIN_TARGET_POINTS, min(MAX_TARGET_POINTS, target_pts))
            sl_dist = min(MAX_SL_POINTS, max(1.80, target_pts * 1.2))
            
            trade_dir = sig
            entry_time = c['time_dt']
            if sig == "LONG":
                sl_price = round(entry_price - sl_dist, 2)
                tp_price = round(entry_price + target_pts, 2)
            else:
                sl_price = round(entry_price + sl_dist, 2)
                tp_price = round(entry_price - target_pts, 2)
                
            in_trade = True

    res_df = pd.DataFrame(trades)
    if res_df.empty:
        print("No trades triggered.")
        return res_df
        
    wins = res_df[res_df['outcome'] == 'WIN']
    losses = res_df[res_df['outcome'] == 'LOSS']
    total_pnl = res_df['pnl'].sum()
    win_rate = len(wins) / len(res_df) * 100
    profit_factor = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else 999.0
    
    print(f"Total Trades: {len(res_df)}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Net Profit: ${total_pnl:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Avg Trade PnL: ${res_df['pnl'].mean():.2f}")
    print("\nSample trades:")
    print(res_df[['entry_time', 'exit_time', 'dir', 'entry', 'exit', 'points', 'pnl', 'outcome']].head(10).to_string(index=False))
    return res_df

# Run Friday: 2026-09-18 00:00 to 23:59 UTC
fri_start = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)
fri_end = datetime(2026, 9, 18, 23, 59, tzinfo=timezone.utc)
backtest_xau_hyper_scalper(fri_start, fri_end, "Friday (2026-09-18)")

# Run Monday: 2026-09-21 00:00 to Now UTC
mon_start = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
mon_end = datetime.now(timezone.utc)
backtest_xau_hyper_scalper(mon_start, mon_end, "Monday (2026-09-21)")
