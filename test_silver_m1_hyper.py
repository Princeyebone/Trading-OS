import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_m1_hyper_optimization():
    if not mt5.initialize():
        return

    # Fetch 8,000 M1 candles (several days of pure M1 scalping data)
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 8000)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    n = len(df)

    lot_size = 0.05
    mult = 5000 * lot_size

    # Parameter grid for M1
    results = []

    for dev in [2.2, 2.5, 2.8]: # wider bands for high-confidence extremes on M1
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + dev * std
        lower = mid - dev * std

        delta = pd.Series(c).diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).values

        for r_low, r_high in [(35, 65), (30, 70), (25, 75)]:
            for target_mode in ['mid', 'half_mid']:
                for sl_mult in [1.5, 2.0, 2.5]:
                    trades = []
                    last_exit = -1

                    for i in range(25, n - 30):
                        if i <= last_exit:
                            continue

                        # Entry conditions: M1 closed outside band with extreme RSI
                        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low)
                        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high)

                        if long_c:
                            entry_p = o[i]
                            if target_mode == 'mid':
                                tp_p = mid[i-1]
                            else:
                                tp_p = entry_p + 0.5 * (mid[i-1] - entry_p)

                            dist = tp_p - entry_p
                            if dist < 0.015:
                                continue
                            sl_p = entry_p - (sl_mult * dist)

                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + 30, n)):
                                if l[k] <= sl_p:
                                    pnl = (sl_p - entry_p) * mult
                                    last_exit = k
                                    break
                                elif h[k] >= tp_p:
                                    pnl = (tp_p - entry_p) * mult
                                    win = True
                                    last_exit = k
                                    break
                            else:
                                pnl = (c[min(i + 30, n) - 1] - entry_p) * mult
                                win = pnl > 0
                                last_exit = min(i + 30, n) - 1
                            trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                        elif short_c:
                            entry_p = o[i]
                            if target_mode == 'mid':
                                tp_p = mid[i-1]
                            else:
                                tp_p = entry_p - 0.5 * (entry_p - mid[i-1])

                            dist = entry_p - tp_p
                            if dist < 0.015:
                                continue
                            sl_p = entry_p + (sl_mult * dist)

                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + 30, n)):
                                if h[k] >= sl_p:
                                    pnl = (entry_p - sl_p) * mult
                                    last_exit = k
                                    break
                                elif l[k] <= tp_p:
                                    pnl = (entry_p - tp_p) * mult
                                    win = True
                                    last_exit = k
                                    break
                            else:
                                pnl = (entry_p - c[min(i + 30, n) - 1]) * mult
                                win = pnl > 0
                                last_exit = min(i + 30, n) - 1
                            trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                    if len(trades) >= 25:
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
                            dw=('win', lambda x: (x == True).sum()),
                            dpnl=('pnl', 'sum')
                        )
                        g_days = (daily['dpnl'] > 0).sum()
                        d_wr = g_days / len(daily) * 100

                        results.append({
                            'dev': dev,
                            'rsi': f"{r_low}/{r_high}",
                            'target': target_mode,
                            'sl_mult': sl_mult,
                            'trades': len(tdf),
                            'wr': wr,
                            'wins': w,
                            'losses': l_cnt,
                            'pf': pf,
                            'pnl': pnl,
                            'g_days': g_days,
                            'tot_days': len(daily),
                            'd_wr': d_wr,
                            'trades_day': len(tdf) / len(daily)
                        })

    rdf = pd.DataFrame(results)
    rdf = rdf.sort_values(by=['wr', 'pf'], ascending=[False, False])
    print("\nTOP 12 M1 SCALPER SETUPS SORTED BY WIN RATE:")
    print(rdf.head(12).to_string(index=False))

run_silver_m1_hyper_optimization()
