import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def generate_full_daily_report():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    rates_m5 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 7000)
    rates_h1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 1000)
    mt5.shutdown()

    df = pd.DataFrame(rates_m5)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    n = len(df)
    mult = 5000 * 0.05

    # H1 EMA50 Macro Filter
    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # M5 Indicators
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.2 * std
    lower = mid - 2.2 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    trades = []
    last_exit_idx = -1

    for i in range(25, n - 25):
        if i <= last_exit_idx:
            continue

        cur_date = df['date'].iloc[i]
        cur_hour = df['hour'].iloc[i]

        if not (7 <= cur_hour <= 18):
            continue

        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (lower_wick[i-1] >= body[i-1]) and (c[i-1] >= h1_ema50[i-1])
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (upper_wick[i-1] >= body[i-1]) and (c[i-1] <= h1_ema50[i-1])

        if long_c:
            entry_p = o[i]
            target_p = mid[i-1]
            target_dist = target_p - entry_p
            if target_dist < 0.03:
                continue
            sl_p = entry_p - (1.2 * target_dist)

            win = False
            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 25, n)):
                if not be_active and h[k] >= entry_p + (0.40 * target_dist):
                    sl_p = entry_p + 0.005
                    be_active = True

                if l[k] <= sl_p:
                    pnl = (sl_p - entry_p) * mult
                    win = pnl > 0
                    last_exit_idx = k
                    break
                elif h[k] >= target_p:
                    pnl = (target_p - entry_p) * mult
                    win = True
                    last_exit_idx = k
                    break
            else:
                pnl = (c[min(i + 25, n) - 1] - entry_p) * mult
                win = pnl > 0
                last_exit_idx = min(i + 25, n) - 1

            trades.append({
                'date': str(cur_date),
                'time': df['time'].iloc[i].strftime('%H:%M'),
                'dir': 'LONG',
                'entry': entry_p,
                'target': target_p,
                'sl': sl_p,
                'win': win,
                'pnl': pnl
            })

        elif short_c:
            entry_p = o[i]
            target_p = mid[i-1]
            target_dist = entry_p - target_p
            if target_dist < 0.03:
                continue
            sl_p = entry_p + (1.2 * target_dist)

            win = False
            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 25, n)):
                if not be_active and l[k] <= entry_p - (0.40 * target_dist):
                    sl_p = entry_p - 0.005
                    be_active = True

                if h[k] >= sl_p:
                    pnl = (entry_p - sl_p) * mult
                    win = pnl > 0
                    last_exit_idx = k
                    break
                elif l[k] <= target_p:
                    pnl = (entry_p - target_p) * mult
                    win = True
                    last_exit_idx = k
                    break
            else:
                pnl = (entry_p - c[min(i + 25, n) - 1]) * mult
                win = pnl > 0
                last_exit_idx = min(i + 25, n) - 1

            trades.append({
                'date': str(cur_date),
                'time': df['time'].iloc[i].strftime('%H:%M'),
                'dir': 'SHORT',
                'entry': entry_p,
                'target': target_p,
                'sl': sl_p,
                'win': win,
                'pnl': pnl
            })

    tdf = pd.DataFrame(trades)

    daily = tdf.groupby('date').agg(
        trades=('win', 'count'),
        wins=('win', lambda x: (x == True).sum()),
        losses=('win', lambda x: (x == False).sum()),
        pnl=('pnl', 'sum')
    ).reset_index()

    daily['win_rate'] = (daily['wins'] / daily['trades']) * 100
    green_days = len(daily[daily['pnl'] > 0])
    red_days = len(daily[daily['pnl'] < 0])

    print("=========================================================================")
    print("  SILVER (XAGUSD) LOSS-EATER HYPER SCALPER: COMPLETE AUDIT RESULTS")
    print("=========================================================================")
    print(f"Total Active Trading Days: {len(daily)}")
    print(f"Green Winning Days       : {green_days} of {len(daily)} ({green_days/len(daily)*100:.1f}%)")
    print(f"Total Trades Taken       : {len(tdf)}")
    print(f"Overall Trade Win Rate   : {tdf['win'].sum()} Wins / {(~tdf['win']).sum()} Losses ({tdf['win'].mean()*100:.1f}%)")
    print(f"Profit Factor            : {tdf[tdf['pnl']>0]['pnl'].sum() / abs(tdf[tdf['pnl']<0]['pnl'].sum()):.2f}")
    print(f"Total Net Profit (0.05 lot): +${tdf['pnl'].sum():,.2f}")

    print("\n" + "=" * 73)
    print("  EXACT DAY-BY-DAY PERFORMANCE BREAKDOWN:")
    print("=" * 73)
    for _, r in daily.iterrows():
        status = "GREEN" if r['pnl'] > 0 else "RED"
        print(f"  {r['date']} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | Win Rate: {r['win_rate']:5.1f}% | PnL: ${r['pnl']:+8.2f} [{status}]")

    print("\n" + "=" * 73)
    print("  DETAILED TRADE LOG (CHRONOLOGICAL):")
    print("=" * 73)
    for _, t in tdf.iterrows():
        status = "WIN " if t['win'] else "LOSS"
        print(f"  {t['date']} {t['time']} | {t['dir']:5} @ {t['entry']:.3f} | TP: {t['target']:.3f} | PnL: ${t['pnl']:+7.2f} [{status}]")

if __name__ == "__main__":
    generate_full_daily_report()
