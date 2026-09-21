import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_m15_search():
    if not mt5.initialize():
        return

    # Fetch 4000 M15 bars (~7-8 weeks of data)
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M15, 0, 4000)
    mt5.shutdown()

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

    # Parameter grid for M15
    for dev in [2.0, 2.2]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + dev * std
        lower = mid - dev * std

        delta = pd.Series(c).diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).values

        for r_low, r_high in [(38, 62), (35, 65), (32, 68)]:
            for sl_ratio in [1.0, 1.2, 1.5]:
                trades = []
                last_exit = -1
                for i in range(25, n - 20):
                    if i <= last_exit:
                        continue

                    long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low)
                    short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high)

                    if long_c:
                        entry_p = o[i]
                        tp_p = mid[i-1]
                        dist = tp_p - entry_p
                        if dist < 0.03:
                            continue
                        sl_p = entry_p - (sl_ratio * dist)
                        win = False
                        pnl = 0.0
                        for k in range(i, min(i + 20, n)):
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
                            pnl = (c[min(i + 20, n) - 1] - entry_p) * mult
                            win = pnl > 0
                            last_exit = min(i + 20, n) - 1
                        trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                    elif short_c:
                        entry_p = o[i]
                        tp_p = mid[i-1]
                        dist = entry_p - tp_p
                        if dist < 0.03:
                            continue
                        sl_p = entry_p + (sl_ratio * dist)
                        win = False
                        pnl = 0.0
                        for k in range(i, min(i + 20, n)):
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
                            pnl = (entry_p - c[min(i + 20, n) - 1]) * mult
                            win = pnl > 0
                            last_exit = min(i + 20, n) - 1
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

                    if wr >= 65.0:
                        print(f"M15 Setup [Dev: {dev}, RSI: {r_low}/{r_high}, SL: {sl_ratio}x Target]")
                        print(f"  Trades: {len(tdf)} | WR: {wr:.1f}% ({w}W vs {l_cnt}L) | PF: {pf:.2f} | Net: +${pnl:,.2f}")
                        print(f"  Daily: {g_days} Green / {len(daily) - g_days} Red ({d_wr:.1f}% Green Days) | Avg Trades/Day: {len(tdf)/len(daily):.1f}")
                        print("-" * 60)

run_silver_m15_search()
