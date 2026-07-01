import MetaTrader5 as mt5
import pandas as pd
import ta

def test_eusdi6_aggro():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return
        
    rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M1, 0, 400)
    if rates is None:
        print("Failed to fetch rates")
        mt5.shutdown()
        return
        
    df = pd.DataFrame(rates)
    df['time_dt'] = pd.to_datetime(df['time'], unit='s')
    
    close = df['close']
    
    # Test dev=1.5
    bb15 = ta.volatility.BollingerBands(close, window=20, window_dev=1.5)
    df['bb_lower_15'] = bb15.bollinger_lband()
    df['bb_upper_15'] = bb15.bollinger_hband()
    
    # Test dev=1.0
    bb10 = ta.volatility.BollingerBands(close, window=20, window_dev=1.0)
    df['bb_lower_10'] = bb10.bollinger_lband()
    df['bb_upper_10'] = bb10.bollinger_hband()
    
    df['rsi'] = ta.momentum.rsi(close, window=14)
    
    sig_15 = 0
    sig_10 = 0
    
    for i in range(25, len(df)):
        price = df.iloc[i]['close']
        rsi = df.iloc[i]['rsi']
        
        # Dev 1.5 checks
        if (price < df.iloc[i]['bb_lower_15'] and rsi < 40) or (price > df.iloc[i]['bb_upper_15'] and rsi > 60):
            sig_15 += 1
            
        # Dev 1.0 checks
        if (price < df.iloc[i]['bb_lower_10'] and rsi < 40) or (price > df.iloc[i]['bb_upper_10'] and rsi > 60):
            sig_10 += 1
            
    print(f"Signals with Dev=1.5 (RSI 40/60): {sig_15}")
    print(f"Signals with Dev=1.0 (RSI 40/60): {sig_10}")
    
    mt5.shutdown()

if __name__ == "__main__":
    test_eusdi6_aggro()
