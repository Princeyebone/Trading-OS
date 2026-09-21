import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_asymmetric_rr():
    if not mt5.initialize():
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 15000)
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

    # Test 1.0 R:R (SL = Target Distance) vs 1.1 R:R
    for sl_mult in [0.9, 1.0, 1.1]:
        trades = []
        last_exit = -1

        for i in range(25, n - 25):
            if i <= last_exit:
                continue

            cur_hour = df['hour'].iloc[i]
            if not (7 <= cur_hour <= 18):
                continue

            long_sig = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30)
            short_sig = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70)

            if long_sig:
                entry_p = o[i]
                tp_p = entry_p + 0.80 * (mid[i-1] - entry_p) # Target closer to mid-band
                dist = tp_p - entry_p
                if dist < 0.02:
                    continue
                sl_p = entry_p - (sl_mult * dist)

                win = False
                pnl = 0.0
                for k in range(i, min(i + 25, n)):
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
                    pnl = (c[min(i + 25, n) - 1] - entry_p) * mult
                    win = pnl > 0
                    last_exit = min(i + 25, n) - 1

                trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

            elif short_sig:
                entry_p = o[i]
                tp_p = entry_p - 0.80 * (entry_p - mid[i-1])
                dist = entry_p - tp_p
                if dist < 0.02:
                    continue
                sl_p = entry_p + (sl_mult * dist)

                win = False
                pnl = 0.0
                for k in range(i, min(i + 25, n)):
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
                    pnl = (entry_p - c[min(i + 25, n) - 1]) * mult
                    win = pnl > 0
                    last_exit = min(i + 25, n) - 1

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
            pnl=('pnl', 'sum')
        )
        g_days = (daily['pnl'] > 0).sum()

        print(f"SL Multiplier = {sl_mult}x:")
        print(f"  Trades: {len(tdf)} | Win Rate: {wr:.1f}% ({w}W vs {l_cnt}L) | PF: {pf:.2f} | PnL: +${pnl:,.2f}")
        print(f"  Daily: {g_days} Green / {len(daily) - g_days} Red ({(g_days/len(daily)*100):.1f}% Green Days)")

run_silver_asymmetric_rr()
