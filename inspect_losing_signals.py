import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def inspect_losing_days():
    if not mt5.initialize():
        return
    r = mt5.copy_rates_from_pos('XAGUSD', mt5.TIMEFRAME_M5, 0, 7000)
    mt5.shutdown()
    df = pd.DataFrame(r)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values; n = len(df)
    mult = 5000 * 0.05

    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.2 * std
    lower = mid - 2.2 * std
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = (100 - (100 / (1 + (gain / (loss + 1e-9))))).values

    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    for i in range(25, n-25):
        d = df['date'].iloc[i]
        if str(d) in ['2026-08-31', '2026-09-10', '2026-09-15', '2026-09-17']:
            hr = df['time'].iloc[i].hour
            if 7 <= hr <= 18:
                long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (lower_wick[i-1] >= body[i-1])
                short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (upper_wick[i-1] >= body[i-1])
                if long_c:
                    print(df['time'].iloc[i], "LONG Signal | Price:", round(o[i], 3), "| BB_Mid:", round(mid[i-1], 3), "| RSI:", round(rsi[i-1], 1))
                elif short_c:
                    print(df['time'].iloc[i], "SHORT Signal | Price:", round(o[i], 3), "| BB_Mid:", round(mid[i-1], 3), "| RSI:", round(rsi[i-1], 1))

inspect_losing_days()
