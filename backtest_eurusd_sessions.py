import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')

SYMBOL = "EURUSD"

def fetch_data(timeframe, num_candles=40000):
    rates = mt5.copy_rates_from_pos(SYMBOL, timeframe, 0, num_candles)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def analyze_trades(trades):
    if not trades:
        return {"total": 0, "win_rate": 0, "profit": 0, "pf": 0}
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    win_rate = len(wins) / len(trades) * 100
    total_profit_pips = sum(trades) * 10000
    
    gross_profit = sum(wins) * 10000 if wins else 0
    gross_loss = abs(sum(losses)) * 10000 if losses else 0
    
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
    
    return {
        "total": len(trades),
        "win_rate": round(win_rate, 2),
        "profit": round(total_profit_pips, 2), 
        "pf": round(pf, 2)
    }

def backtest_session_momentum(df, start_hour, end_hour):
    c = df['close']
    high = df['high']
    low = df['low']
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    
    tr = pd.concat([high - low, abs(high - c.shift()), abs(low - c.shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    trades = []
    current_pos = None
    entry_price = sl = tp = 0
    pending_limit = None
    
    for i in range(200, len(df)):
        price = df['open'].iloc[i]
        curr_low = df['low'].iloc[i]
        curr_high = df['high'].iloc[i]
        hour = df['time'].iloc[i].hour
        
        if current_pos:
            if current_pos == "LONG":
                if curr_low <= sl:
                    trades.append(sl - entry_price)
                    current_pos = None
                elif curr_high >= tp:
                    trades.append(tp - entry_price)
                    current_pos = None
            elif current_pos == "SHORT":
                if curr_high >= sl:
                    trades.append(entry_price - sl)
                    current_pos = None
                elif curr_low <= tp:
                    trades.append(entry_price - tp)
                    current_pos = None
            continue
            
        if pending_limit:
            if i > pending_limit['expires_idx']:
                pending_limit = None
            else:
                if pending_limit['direction'] == "LONG" and curr_low <= pending_limit['price']:
                    current_pos = "LONG"
                    entry_price = pending_limit['price']
                    sl = pending_limit['sl']
                    tp = pending_limit['tp']
                    pending_limit = None
                    continue
                elif pending_limit['direction'] == "SHORT" and curr_high >= pending_limit['price']:
                    current_pos = "SHORT"
                    entry_price = pending_limit['price']
                    sl = pending_limit['sl']
                    tp = pending_limit['tp']
                    pending_limit = None
                    continue
                    
        is_in_session = False
        if start_hour < end_hour:
            is_in_session = start_hour <= hour < end_hour
        else:
            is_in_session = hour >= start_hour or hour < end_hour
            
        if not is_in_session:
            continue
            
        prev1 = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        
        if prev2['close'] < prev2['open'] and prev1['close'] > prev1['open'] and prev1['close'] > prev2['high']:
            if prev1['close'] > prev1['ema200']:
                impulse_range = prev1['high'] - prev1['low']
                if impulse_range > prev1['atr']: 
                    limit_price = prev1['low'] + (impulse_range * 0.5)
                    sl_price = limit_price - (prev1['atr'] * 1.5)
                    tp_price = limit_price + (prev1['atr'] * 2.0)
                    
                    pending_limit = {
                        'direction': 'LONG',
                        'price': limit_price,
                        'sl': sl_price,
                        'tp': tp_price,
                        'expires_idx': i + 3
                    }
                    
        elif prev2['close'] > prev2['open'] and prev1['close'] < prev1['open'] and prev1['close'] < prev2['low']:
            if prev1['close'] < prev1['ema200']:
                impulse_range = prev1['high'] - prev1['low']
                if impulse_range > prev1['atr']:
                    limit_price = prev1['high'] - (impulse_range * 0.5)
                    sl_price = limit_price + (prev1['atr'] * 1.5)
                    tp_price = limit_price - (prev1['atr'] * 2.0)
                    
                    pending_limit = {
                        'direction': 'SHORT',
                        'price': limit_price,
                        'sl': sl_price,
                        'tp': tp_price,
                        'expires_idx': i + 3
                    }
                    
    return analyze_trades(trades)


def backtest_asian_breakout(df):
    trades = []
    current_pos = None
    entry_price = sl = tp = 0
    asian_high = None
    asian_low = None
    pending_long = None
    pending_short = None
    
    for i in range(1, len(df)):
        price = df['open'].iloc[i]
        curr_low = df['low'].iloc[i]
        curr_high = df['high'].iloc[i]
        curr_time = df['time'].iloc[i]
        hour = curr_time.hour
        
        if current_pos:
            if current_pos == "LONG":
                if curr_low <= sl:
                    trades.append(sl - entry_price)
                    current_pos = None
                elif curr_high >= tp:
                    trades.append(tp - entry_price)
                    current_pos = None
            elif current_pos == "SHORT":
                if curr_high >= sl:
                    trades.append(entry_price - sl)
                    current_pos = None
                elif curr_low <= tp:
                    trades.append(entry_price - tp)
                    current_pos = None
            continue
            
        if hour == 16:
            pending_long = None
            pending_short = None
            
        if 0 <= hour < 7:
            if hour == 0 and curr_time.minute == 0:
                asian_high = curr_high
                asian_low = curr_low
            else:
                if asian_high is not None:
                    asian_high = max(asian_high, curr_high)
                    asian_low = min(asian_low, curr_low)
        
        if hour == 7 and curr_time.minute == 0:
            if asian_high is not None and asian_low is not None:
                range_size_pips = (asian_high - asian_low) * 10000
                if range_size_pips < 30:
                    pending_long = asian_high + 0.0002 
                    pending_short = asian_low - 0.0002 
                
        if pending_long and curr_high >= pending_long:
            current_pos = "LONG"
            entry_price = pending_long
            sl = entry_price - 0.0015 
            tp = entry_price + 0.0020 
            pending_long = None
            pending_short = None 
            continue
            
        if pending_short and curr_low <= pending_short:
            current_pos = "SHORT"
            entry_price = pending_short
            sl = entry_price + 0.0015
            tp = entry_price - 0.0020
            pending_long = None
            pending_short = None
            continue
            
    return analyze_trades(trades)


def run_all():
    if not mt5.initialize():
        print("MT5 init failed")
        return
        
    print("Fetching M5 data...")
    m5_df = fetch_data(mt5.TIMEFRAME_M5, 30000)
    
    print("Fetching M15 data...")
    m15_df = fetch_data(mt5.TIMEFRAME_M15, 10000)
    
    if m5_df.empty or m15_df.empty:
        print("Failed to fetch data")
        return
        
    print("\nEURUSD SCALPING STRATEGY BACKTEST RESULTS")
    print("============================================================")
    
    london_ny = backtest_session_momentum(m5_df.copy(), start_hour=7, end_hour=16)
    asian = backtest_session_momentum(m5_df.copy(), start_hour=0, end_hour=7)
    breakout = backtest_asian_breakout(m15_df.copy())
    
    print(f"[M5 Momentum] London/NY Session (07-16) | Trades: {london_ny['total']:<4} | Win Rate: {london_ny['win_rate']:<5}% | Profit: {london_ny['profit']:>6.2f} pips | PF: {london_ny['pf']:>4.2f}")
    print(f"[M5 Momentum] Asian Session (00-07)     | Trades: {asian['total']:<4} | Win Rate: {asian['win_rate']:<5}% | Profit: {asian['profit']:>6.2f} pips | PF: {asian['pf']:>4.2f}")
    print(f"[M15] Asian Range Breakout              | Trades: {breakout['total']:<4} | Win Rate: {breakout['win_rate']:<5}% | Profit: {breakout['profit']:>6.2f} pips | PF: {breakout['pf']:>4.2f}")

    mt5.shutdown()

if __name__ == '__main__':
    run_all()
