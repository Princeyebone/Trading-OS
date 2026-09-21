import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_hf_mastery():
    if not mt5.initialize():
        return

    rates_m1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 20000)
    rates_h1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 1000)
    mt5.shutdown()

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    n = len(df)
    lot_size = 0.05
    mult = 5000 * lot_size

    # H1 Trend filter
    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema = df['h1_ema50'].values

    # Test M1 Hyper-Scalper setups with Trend Filter
    # Dev 2.2 to 2.4, RSI(7) 30/70, Target 0.6 to 0.8
    results = []

    for dev in [2.0, 2.2, 2.4]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + dev * std
        lower = mid - dev * std

        delta = pd.Series(c).diff()
        gain = delta.clip(lower=0).rolling(7).mean()
        loss = (-delta.clip(upper=0)).rolling(7).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).values

        for tp_frac in [0.5, 0.7, 0.9]:
            for sl_m in [1.2, 1.5, 1.8]:
                for use_h1 in [False, True]:
                    trades = []
                    last_exit = -1

                    for i in range(25, n - 20):
                        if i <= last_exit:
                            continue

                        hr = df['hour'].iloc[i]
                        if not (6 <= hr <= 19):
                            continue

                        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30)
                        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70)

                        if use_h1:
                            long_c = long_c and (c[i-1] >= h1_ema[i-1] - 0.25)
                            short_c = short_c and (c[i-1] <= h1_ema[i-1] + 0.25)

                        if long_c:
                            entry = o[i]
                            dist = mid[i-1] - entry
                            if dist < 0.025:
                                continue
                            tp = entry + (tp_frac * dist)
                            sl = entry - (sl_m * (tp - entry))

                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + 20, n)):
                                if l[k] <= sl:
                                    pnl = (sl - entry) * mult
                                    last_exit = k
                                    break
                                elif h[k] >= tp:
                                    pnl = (tp - entry) * mult
                                    win = True
                                    last_exit = k
                                    break
                            else:
                                pnl = (c[min(i + 20, n) - 1] - entry) * mult
                                win = pnl > 0
                                last_exit = min(i + 20, n) - 1

                            trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                        elif short_c:
                            entry = o[i]
                            dist = entry - mid[i-1]
                            if dist < 0.025:
                                continue
                            tp = entry - (tp_frac * dist)
                            sl = entry + (sl_m * (entry - tp))

                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + 20, n)):
                                if h[k] >= sl:
                                    pnl = (entry - sl) * mult
                                    last_exit = k
                                    break
                                elif l[k] <= tp:
                                    pnl = (entry - tp) * mult
                                    win = True
                                    last_exit = k
                                    break
                            else:
                                pnl = (entry - c[min(i + 20, n) - 1]) * mult
                                win = pnl > 0
                                last_exit = min(i + 20, n) - 1

                            trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                    if len(trades) >= 30:
                        tdf = pd.DataFrame(trades)
                        daily = tdf.groupby('date').agg(
                            trades=('win', 'count'),
                            wins=('win', lambda x: (x == True).sum()),
                            losses=('win', lambda x: (x == False).sum()),
                            pnl=('pnl', 'sum')
                        )
                        w_gt_l = (daily['wins'] > daily['losses']).sum()
                        g_days = (daily['pnl'] > 0).sum()
                        tot_days = len(daily)

                        results.append({
                            'dev': dev,
                            'tp_f': tp_frac,
                            'sl_m': sl_m,
                            'h1': use_h1,
                            'trades': len(tdf),
                            'trades_day': len(tdf) / tot_days,
                            'wr': tdf['win'].mean() * 100,
                            'w_gt_l_days': w_gt_l,
                            'green_days': g_days,
                            'total_days': tot_days,
                            'w_gt_l_pct': (w_gt_l / tot_days) * 100,
                            'green_pct': (g_days / tot_days) * 100,
                            'pnl': tdf['pnl'].sum()
                        })

    rdf = pd.DataFrame(results).sort_values(by=['green_pct', 'w_gt_l_pct', 'pnl'], ascending=[False, False, False])
    print("TOP 10 HIGH-FREQUENCY SETUPS RANKED BY GREEN DAYS % & WINS > LOSSES %:")
    print(rdf[['dev', 'tp_f', 'sl_m', 'h1', 'trades', 'trades_day', 'wr', 'w_gt_l_days', 'green_days', 'total_days', 'w_gt_l_pct', 'green_pct', 'pnl']].head(10).to_string(index=False))

run_silver_hf_mastery()
