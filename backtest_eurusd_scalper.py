import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')

SYMBOL = "EURUSD"

def fetch_data(timeframe, num_candles=30000):
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

def backtest_m5_momentum_scalper(df):
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
                    
        prev1 = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        
        # Bullish Engulfing
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
                    
        # Bearish Engulfing
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

def backtest_m1_hyper_scalper(df):
    c = df['close']
    high = df['high']
    low = df['low']
    df['ema20'] = c.ewm(span=20, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    
    tr = pd.concat([high - low, abs(high - c.shift()), abs(low - c.shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    trades = []
    current_pos = None
    entry_price = sl = tp = 0
    
    for i in range(50, len(df)):
        curr_low = df['low'].iloc[i]
        curr_high = df['high'].iloc[i]
        
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
            
        prev = df.iloc[i-1]
        
        trend_up = prev['ema20'] > prev['ema50']
        trend_down = prev['ema20'] < prev['ema50']
        
        candle_range = prev['high'] - prev['low']
        if candle_range <= 0.00005: 
            continue
            
        lower_wick = min(prev['open'], prev['close']) - prev['low']
        upper_wick = prev['high'] - max(prev['open'], prev['close'])
        
        bullish_rejection = (lower_wick / candle_range) > 0.5
        bearish_rejection = (upper_wick / candle_range) > 0.5
        
        dist_to_ema20 = abs(prev['close'] - prev['ema20'])
        is_near = dist_to_ema20 < 0.0002
        
        sl_dist = max(0.0003, prev['atr'] * 0.8)
        tp_dist = sl_dist * 1.5
        
        if trend_up and is_near and bullish_rejection:
            current_pos = "LONG"
            entry_price = df['open'].iloc[i]
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
            
        elif trend_down and is_near and bearish_rejection:
            current_pos = "SHORT"
            entry_price = df['open'].iloc[i]
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist
            
    return analyze_trades(trades)

def run_all():
    if not mt5.initialize():
        print("MT5 init failed")
        return
        
    print("Fetching M5 data...")
    m5_df = fetch_data(mt5.TIMEFRAME_M5, 30000)
    
    print("Fetching M1 data...")
    m1_df = fetch_data(mt5.TIMEFRAME_M1, 30000)
    
    if m5_df.empty or m1_df.empty:
        print("Failed to fetch data")
        return
        
    print("\nEURUSD SCALPING STRATEGY BACKTEST RESULTS")
    print("=" * 60)
    
    m5_res = backtest_m5_momentum_scalper(m5_df)
    m1_res = backtest_m1_hyper_scalper(m1_df)
    
    print(f"[M5] Momentum Scalper | Trades: {m5_res['total']:<4} | Win Rate: {m5_res['win_rate']:<5}% | Profit: {m5_res['profit']:>6.2f} pips | PF: {m5_res['pf']:>4.2f}")
    print(f"[M1] Hyper Scalper    | Trades: {m1_res['total']:<4} | Win Rate: {m1_res['win_rate']:<5}% | Profit: {m1_res['profit']:>6.2f} pips | PF: {m1_res['pf']:>4.2f}")

    mt5.shutdown()

if __name__ == '__main__':
    run_all()
