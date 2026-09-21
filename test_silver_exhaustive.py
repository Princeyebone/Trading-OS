import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_exhaustive_optimization():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    # Fetch last 8,000 M5 candles (~6 weeks of tick/candle data)
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 8000)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print("No rates returned")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    n = len(df)

    lot_size = 0.05
    mult = 5000 * lot_size # $250 per $1.00 move

    # Indicators
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.insert(tr, 0, h[0] - l[0])
    atr = pd.Series(tr).rolling(14).mean().values

    # RSI(14)
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    # ADX(14) on M5
    up_move = np.insert(h[1:] - h[:-1], 0, 0)
    down_move = np.insert(l[:-1] - l[1:], 0, 0)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    alpha = 1.0 / 14.0
    tr_smooth = pd.Series(tr).ewm(alpha=alpha, adjust=False).mean().values
    plus_di = 100 * (pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean().values / (tr_smooth + 1e-9))
    minus_di = 100 * (pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean().values / (tr_smooth + 1e-9))
    dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9))
    adx = pd.Series(dx).ewm(alpha=alpha, adjust=False).mean().values

    # Higher timeframe trend filter: 200 EMA on M5 (~16 hour moving trend)
    ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().values
    ema50 = pd.Series(c).ewm(span=50, adjust=False).mean().values

    # Candle wicks
    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    results = []

    # Grid search across all key levers:
    # 1. BB Dev: [2.0, 2.2, 2.4]
    # 2. RSI Oversold/Overbought: [(35, 65), (30, 70), (28, 72)]
    # 3. Rejection Wick threshold: [1.0x body, 1.5x body]
    # 4. Target: [0.7x mid, 0.85x mid, 1.0x mid]
    # 5. Break-Even Trigger: [0.3x, 0.4x target distance]
    # 6. Stop Loss ratio: [0.8x, 1.0x, 1.2x target distance]
    # 7. ADX Trend Runaway filter: [None, ADX < 30, ADX < 25]

    for dev in [2.0, 2.2, 2.4]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + dev * std
        lower = mid - dev * std

        for r_low, r_high in [(32, 68), (28, 72)]:
            for wick_ratio in [1.0, 1.3]:
                for tp_ratio in [0.75, 1.0]: # 0.75 reaches TP much faster and more reliably
                    for be_trig in [0.35, 0.45]:
                        for sl_ratio in [0.9, 1.1]:
                            for max_adx in [0, 32]:
                                trades = []
                                last_exit_idx = -1

                                for i in range(25, n - 25):
                                    if i <= last_exit_idx:
                                        continue

                                    cur_hour = df['hour'].iloc[i]
                                    if not (7 <= cur_hour <= 18):
                                        continue

                                    if max_adx > 0 and adx[i-1] > max_adx:
                                        continue

                                    long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low) and (lower_wick[i-1] >= wick_ratio * body[i-1])
                                    short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high) and (upper_wick[i-1] >= wick_ratio * body[i-1])

                                    if long_c:
                                        entry_p = o[i]
                                        full_dist = mid[i-1] - entry_p
                                        if full_dist < 0.03:
                                            continue
                                        tp_p = entry_p + (tp_ratio * full_dist)
                                        target_dist = tp_p - entry_p
                                        sl_p = entry_p - (sl_ratio * target_dist)

                                        win = False
                                        pnl = 0.0
                                        be_active = False

                                        for k in range(i, min(i + 25, n)):
                                            if not be_active and h[k] >= entry_p + (be_trig * target_dist):
                                                sl_p = entry_p + 0.005
                                                be_active = True

                                            if l[k] <= sl_p:
                                                pnl = (sl_p - entry_p) * mult
                                                win = pnl > 0
                                                last_exit_idx = k
                                                break
                                            elif h[k] >= tp_p:
                                                pnl = (tp_p - entry_p) * mult
                                                win = True
                                                last_exit_idx = k
                                                break
                                        else:
                                            pnl = (c[min(i + 25, n) - 1] - entry_p) * mult
                                            win = pnl > 0
                                            last_exit_idx = min(i + 25, n) - 1

                                        trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                                    elif short_c:
                                        entry_p = o[i]
                                        full_dist = entry_p - mid[i-1]
                                        if full_dist < 0.03:
                                            continue
                                        tp_p = entry_p - (tp_ratio * full_dist)
                                        target_dist = entry_p - tp_p
                                        sl_p = entry_p + (sl_ratio * target_dist)

                                        win = False
                                        pnl = 0.0
                                        be_active = False

                                        for k in range(i, min(i + 25, n)):
                                            if not be_active and l[k] <= entry_p - (be_trig * target_dist):
                                                sl_p = entry_p - 0.005
                                                be_active = True

                                            if h[k] >= sl_p:
                                                pnl = (entry_p - sl_p) * mult
                                                win = pnl > 0
                                                last_exit_idx = k
                                                break
                                            elif l[k] <= tp_p:
                                                pnl = (entry_p - tp_p) * mult
                                                win = True
                                                last_exit_idx = k
                                                break
                                        else:
                                            pnl = (entry_p - c[min(i + 25, n) - 1]) * mult
                                            win = pnl > 0
                                            last_exit_idx = min(i + 25, n) - 1

                                        trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                                if len(trades) >= 20:
                                    tdf = pd.DataFrame(trades)
                                    w = (tdf['win'] == True).sum()
                                    l_cnt = (tdf['win'] == False).sum()
                                    wr = w / len(tdf) * 100
                                    pnl = tdf['pnl'].sum()
                                    gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
                                    gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
                                    pf = gp / (gl if gl > 0 else 1.0)

                                    daily = tdf.groupby('date').agg(
                                        cnt=('win', 'count'),
                                        w=('win', lambda x: (x == True).sum()),
                                        dpnl=('pnl', 'sum')
                                    )
                                    g_days = (daily['dpnl'] > 0).sum()
                                    r_days = (daily['dpnl'] < 0).sum()
                                    d_wr = g_days / len(daily) * 100

                                    results.append({
                                        'dev': dev,
                                        'rsi': f"{r_low}/{r_high}",
                                        'wick': wick_ratio,
                                        'tp_r': tp_ratio,
                                        'be': be_trig,
                                        'sl': sl_ratio,
                                        'adx': max_adx,
                                        'trades': len(tdf),
                                        'wr': wr,
                                        'wins': w,
                                        'losses': l_cnt,
                                        'pf': pf,
                                        'pnl': pnl,
                                        'g_days': g_days,
                                        'r_days': r_days,
                                        'd_wr': d_wr
                                    })

    rdf = pd.DataFrame(results)
    print(f"Total configurations examined: {len(rdf)}")
    
    # Sort primarily by Profit Factor, then Daily Win Rate, then Win Rate
    top = rdf.sort_values(by=['pf', 'd_wr', 'wr'], ascending=[False, False, False])
    print("\nTOP 10 ABSOLUTE BEST SILVER SETUPS (Ranked by Profit Factor & Green Day Consistency):")
    print(top.head(10).to_string(index=False))

if __name__ == "__main__":
    run_silver_exhaustive_optimization()
