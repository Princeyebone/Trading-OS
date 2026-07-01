import MetaTrader5 as mt5
import pandas as pd
import ta
import time

def test_eusd_engines():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return
        
    rates_m1 = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M1, 0, 300)
    rates_m5 = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M5, 0, 100)
    
    if rates_m1 is None or rates_m5 is None:
        print("Data fetch failed")
        mt5.shutdown()
        return
        
    m1_data = pd.DataFrame(rates_m1)
    m5_data = pd.DataFrame(rates_m5)
    
    m1_data['time_dt'] = pd.to_datetime(m1_data['time'], unit='s')
    m5_data['time_dt'] = pd.to_datetime(m5_data['time'], unit='s')
    
    m1_close = m1_data['close']
    m5_close = m5_data['close']
    
    # EUSDI6 Indicators
    bb = ta.volatility.BollingerBands(m1_close, window=20, window_dev=2.0)
    m1_data['bb_upper'] = bb.bollinger_hband()
    m1_data['bb_lower'] = bb.bollinger_lband()
    
    # EUSDI7 Indicators
    m5_data['ema20'] = ta.trend.ema_indicator(m5_close, window=20)
    m5_data['ema50'] = ta.trend.ema_indicator(m5_close, window=50)
    
    m1_data['rsi'] = ta.momentum.rsi(m1_close, window=14)
    
    high_low = m1_data['high'] - m1_data['low']
    high_close = (m1_data['high'] - m1_data['close'].shift()).abs()
    low_close = (m1_data['low'] - m1_data['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    m1_data['atr'] = true_range.rolling(14).mean()
    m1_data['candle_size'] = true_range
    
    i6_signals = 0
    i7_signals = 0
    
    print(f"Scanning {len(m1_data)} M1 candles for EUSDI6 and EUSDI7...")
    
    for i in range(30, len(m1_data)-1):
        row = m1_data.iloc[i]
        price = row['close']
        bb_upper = row['bb_upper']
        bb_lower = row['bb_lower']
        rsi = row['rsi']
        atr = row['atr']
        c_size = row['candle_size']
        time_val = row['time']
        
        # Match M5 time
        m5_row = m5_data[m5_data['time'] <= time_val].iloc[-1]
        m5_ema20 = m5_row['ema20']
        m5_ema50 = m5_row['ema50']
        
        # EUSDI6 Logic
        if (price < bb_lower and rsi < 40) or (price > bb_upper and rsi > 60):
            i6_signals += 1
            
        # EUSDI7 Logic
        m5_trend = "NONE"
        if m5_ema20 > m5_ema50: m5_trend = "BULLISH"
        elif m5_ema20 < m5_ema50: m5_trend = "BEARISH"
        
        vol_burst = c_size > (atr * 1.5)
        
        if (m5_trend == "BULLISH" and vol_burst and rsi > 55) or \
           (m5_trend == "BEARISH" and vol_burst and rsi < 45):
            i7_signals += 1
            
    print(f"EUSDI6 (Mean Reversion) Signals in last 300 minutes: {i6_signals}")
    print(f"EUSDI7 (Momentum) Signals in last 300 minutes: {i7_signals}")
    
    mt5.shutdown()

if __name__ == "__main__":
    test_eusd_engines()
