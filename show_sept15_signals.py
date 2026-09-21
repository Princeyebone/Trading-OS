import MetaTrader5 as mt5
import pandas as pd

def show_sept15_signals():
    if not mt5.initialize():
        return
    r_m1 = mt5.copy_rates_from_pos('XAGUSD', mt5.TIMEFRAME_M1, 0, 20000)
    r_h1 = mt5.copy_rates_from_pos('XAGUSD', mt5.TIMEFRAME_H1, 0, 1000)
    mt5.shutdown()

    df = pd.DataFrame(r_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df_h1 = pd.DataFrame(r_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')

    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.4 * std
    lower = mid - 2.4 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values
    h1_ema50 = df['h1_ema50'].values

    sub = df[df['date'] == pd.to_datetime('2026-09-15').date()]
    start_idx = sub.index[0]
    end_idx = sub.index[-1]

    for i in range(start_idx, end_idx):
        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (c[i-1] >= h1_ema50[i-1] - 0.25)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (c[i-1] <= h1_ema50[i-1] + 0.25)
        if long_c or short_c:
            side = 'BUY' if long_c else 'SELL'
            t_str = df['time'].iloc[i].strftime('%H:%M')
            print(f"{t_str} | {side} @ {o[i]:.3f} | rsi={rsi[i-1]:.1f} | h1_ema={h1_ema50[i-1]:.3f} | mid={mid[i-1]:.3f}")

if __name__ == "__main__":
    show_sept15_signals()
