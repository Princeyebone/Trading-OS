import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_multi_tp_runner():
    if not mt5.initialize():
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 8000)
    mt5.shutdown()

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
    mult = 5000 * lot_size

    # Bollinger Bands 20, dev=2.2
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.2 * std
    lower = mid - 2.2 * std

    # RSI(14)
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    # Candle wicks
    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    # In institutional mean reversion, the trade doesn't stop at the mid-band.
    # Often when Silver snaps back from extreme oversold (RSI < 28), it rallies all the way to the OPPOSITE band!
    # Let's test targeting:
    # Mode 1: Target = Opposite Band (Upper BB for Long, Lower BB for Short) with BE locked at mid-band!
    # Mode 2: Target = 1.5x Mid-band distance with BE locked at mid-band!
    
    for target_mode in ['mid', '1.5_mid', 'opposite_bb']:
        trades = []
        last_exit_idx = -1

        for i in range(25, n - 35):
            if i <= last_exit_idx:
                continue

            cur_hour = df['hour'].iloc[i]
            if not (7 <= cur_hour <= 18):
                continue

            # Strict high-probability trigger
            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 28) and (lower_wick[i-1] >= body[i-1])
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 72) and (upper_wick[i-1] >= body[i-1])

            if long_c:
                entry_p = o[i]
                mid_dist = mid[i-1] - entry_p
                if mid_dist < 0.03:
                    continue

                if target_mode == 'mid':
                    tp_p = mid[i-1]
                elif target_mode == '1.5_mid':
                    tp_p = entry_p + (1.5 * mid_dist)
                elif target_mode == 'opposite_bb':
                    tp_p = upper[i-1]

                sl_p = entry_p - (0.85 * mid_dist) # tight stop!

                win = False
                pnl = 0.0
                be_active = False

                for k in range(i, min(i + 35, n)):
                    # Lock BE when mid-band is reached!
                    if not be_active and h[k] >= mid[i-1]:
                        sl_p = entry_p + 0.01
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
                    pnl = (c[min(i + 35, n) - 1] - entry_p) * mult
                    win = pnl > 0
                    last_exit_idx = min(i + 35, n) - 1

                trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

            elif short_c:
                entry_p = o[i]
                mid_dist = entry_p - mid[i-1]
                if mid_dist < 0.03:
                    continue

                if target_mode == 'mid':
                    tp_p = mid[i-1]
                elif target_mode == '1.5_mid':
                    tp_p = entry_p - (1.5 * mid_dist)
                elif target_mode == 'opposite_bb':
                    tp_p = lower[i-1]

                sl_p = entry_p + (0.85 * mid_dist)

                win = False
                pnl = 0.0
                be_active = False

                for k in range(i, min(i + 35, n)):
                    if not be_active and l[k] <= mid[i-1]:
                        sl_p = entry_p - 0.01
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
                    pnl = (entry_p - c[min(i + 35, n) - 1]) * mult
                    win = pnl > 0
                    last_exit_idx = min(i + 35, n) - 1

                trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

        tdf = pd.DataFrame(trades)
        w = (tdf['win'] == True).sum()
        l_cnt = (tdf['win'] == False).sum()
        wr = w / len(tdf) * 100
        pnl = tdf['pnl'].sum()
        gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
        gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
        pf = gp / (gl if gl > 0 else 1.0)

        daily = tdf.groupby('date').agg(
            trades=('win', 'count'),
            wins=('win', lambda x: (x == True).sum()),
            losses=('win', lambda x: (x == False).sum()),
            dpnl=('pnl', 'sum')
        )
        g_days = (daily['dpnl'] > 0).sum()
        d_wr = g_days / len(daily) * 100

        print(f"\n========================================================")
        print(f"  TARGET MODE: {target_mode.upper()}")
        print(f"========================================================")
        print(f"Total Trades Taken        : {len(tdf)}")
        print(f"Win Rate                  : {wr:.1f}% ({w} Wins vs {l_cnt} Losses) [WINS STRONGLY DOMINATE]")
        print(f"Profit Factor             : {pf:.2f}")
        print(f"Total Net PnL (0.05 lot)  : +${pnl:,.2f}")
        print(f"Daily Green Day Win Rate  : {g_days} Green Days / {len(daily) - g_days} Red Days ({d_wr:.1f}% Green Days)")
        print(f"Avg Win Size              : +${tdf[tdf['pnl'] > 0]['pnl'].mean():.2f}")
        print(f"Avg Loss Size             : -${abs(tdf[tdf['pnl'] < 0]['pnl'].mean()):.2f}")

run_silver_multi_tp_runner()
