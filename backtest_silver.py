import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')

SYMBOL = "XAGUSD"

def fetch_data(timeframe, num_candles=20000):
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
    total_profit = sum(trades)
    
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
    
    return {
        "total": len(trades),
        "win_rate": round(win_rate, 2),
        "profit": round(total_profit, 2), # points/dollars per unit
        "pf": round(pf, 2)
    }

def backtest_macd(df):
    c = df['close']
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['prev_macd'] = df['macd'].shift(1)
    
    trades = []
    current_pos = None
    entry_price = 0
    
    for i in range(2, len(df)):
        curr_macd = df['macd'].iloc[i-1]
        prev_macd = df['prev_macd'].iloc[i-1]
        price = df['open'].iloc[i]
        
        if prev_macd <= 0 and curr_macd > 0: # Bullish Cross
            if current_pos == "SHORT":
                trades.append(entry_price - price)
                current_pos = None
            if current_pos != "LONG":
                current_pos = "LONG"
                entry_price = price
                
        elif prev_macd >= 0 and curr_macd < 0: # Bearish Cross
            if current_pos == "LONG":
                trades.append(price - entry_price)
                current_pos = None
            if current_pos != "SHORT":
                current_pos = "SHORT"
                entry_price = price
                
    if current_pos == "LONG": trades.append(df['close'].iloc[-1] - entry_price)
    elif current_pos == "SHORT": trades.append(entry_price - df['close'].iloc[-1])
         
    return analyze_trades(trades)

def backtest_bb_mr(df):
    c = df['close']
    sma = c.rolling(20).mean()
    std = c.rolling(20).std()
    
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    
    high = df['high']
    low = df['low']
    tr = pd.concat([high - low, abs(high - c.shift()), abs(low - c.shift())], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    
    df['lower_bb'] = sma - (2 * std)
    df['upper_bb'] = sma + (2 * std)
    df['sma'] = sma
    df['rsi'] = 100 - (100 / (1 + rs))
    df['atr'] = atr
    
    trades = []
    current_pos = None
    entry_price = sl = tp = 0
    
    for i in range(21, len(df)):
        if current_pos:
            curr_low = df['low'].iloc[i]
            curr_high = df['high'].iloc[i]
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
            
        prev_low = df['low'].iloc[i-1]
        prev_high = df['high'].iloc[i-1]
        prev_lbb = df['lower_bb'].iloc[i-1]
        prev_ubb = df['upper_bb'].iloc[i-1]
        prev_sma = df['sma'].iloc[i-1]
        prev_rsi = df['rsi'].iloc[i-1]
        prev_atr = df['atr'].iloc[i-1]
        
        price = df['open'].iloc[i]
        
        # Long condition
        if prev_low < prev_lbb and prev_rsi < 30:
            current_pos = "LONG"
            entry_price = price
            tp = prev_sma
            sl = entry_price - (prev_atr * 1.5)
        # Short condition
        elif prev_high > prev_ubb and prev_rsi > 70:
            current_pos = "SHORT"
            entry_price = price
            tp = prev_sma
            sl = entry_price + (prev_atr * 1.5)
            
    return analyze_trades(trades)

def backtest_ema_pullback(df):
    c = df['close']
    df['ema9'] = c.ewm(span=9, adjust=False).mean()
    df['ema21'] = c.ewm(span=21, adjust=False).mean()
    
    high, low = df['high'], df['low']
    tr = pd.concat([high - low, abs(high - c.shift()), abs(low - c.shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    trades = []
    current_pos = None
    entry_price = sl = tp = 0
    
    for i in range(25, len(df)):
        if current_pos:
            curr_low = df['low'].iloc[i]
            curr_high = df['high'].iloc[i]
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
            
        prev_ema9 = df['ema9'].iloc[i-1]
        prev_ema21 = df['ema21'].iloc[i-1]
        prev_low = df['low'].iloc[i-1]
        prev_high = df['high'].iloc[i-1]
        prev_atr = df['atr'].iloc[i-1]
        price = df['open'].iloc[i]
        
        if prev_ema9 > prev_ema21 and prev_low <= prev_ema21:
            current_pos = "LONG"
            entry_price = price
            sl = entry_price - (prev_atr * 1.5)
            tp = entry_price + (prev_atr * 2.0)
        elif prev_ema9 < prev_ema21 and prev_high >= prev_ema21:
            current_pos = "SHORT"
            entry_price = price
            sl = entry_price + (prev_atr * 1.5)
            tp = entry_price - (prev_atr * 2.0)
            
    return analyze_trades(trades)

def run_all():
    if not mt5.initialize():
        print("MT5 init failed")
        return
        
    timeframes = {
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1
    }
    
    results = []
    # Use 30000 candles to get ~ 100 days of M5 data or ~1 year of M15 data
    num_candles = 30000
    
    print("XAGUSD STRATEGY BACKTEST RESULTS")
    print("=" * 60)
    for tf_name, tf in timeframes.items():
        df = fetch_data(tf, num_candles)
        if df.empty:
            print(f"Failed to fetch {tf_name} data.")
            continue
            
        macd_res = backtest_macd(df.copy())
        bb_res = backtest_bb_mr(df.copy())
        ema_res = backtest_ema_pullback(df.copy())
        
        results.append((tf_name, "MACD Trend", macd_res))
        results.append((tf_name, "BB Mean Reversion", bb_res))
        results.append((tf_name, "EMA Pullback", ema_res))
        
    for tf_name, strat, res in results:
        print(f"[{tf_name}] {strat.ljust(18)} | Trades: {res['total']:<4} | Win Rate: {res['win_rate']:<5}% | Profit: {res['profit']:>6.2f} pts | PF: {res['pf']:>4.2f}")
        
    mt5.shutdown()

if __name__ == '__main__':
    run_all()
