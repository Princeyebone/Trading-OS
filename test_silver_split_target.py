import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_split_target_mastery():
    if not mt5.initialize():
        return

    # Fetch 8000 M5 candles
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

    trades = []
    last_exit_idx = -1

    for i in range(25, n - 35):
        if i <= last_exit_idx:
            continue

        cur_hour = df['hour'].iloc[i]
        if not (7 <= cur_hour <= 18):
            continue

        # Pinpoint entry: Bollinger 2.2 breach, RSI < 28 or > 72, rejection wick
        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 28) and (lower_wick[i-1] >= body[i-1])
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 72) and (upper_wick[i-1] >= body[i-1])

        if long_c:
            entry_p = o[i]
            mid_dist = mid[i-1] - entry_p
            if mid_dist < 0.03:
                continue

            tp1 = mid[i-1]
            tp2 = upper[i-1] # opposite band runner
            sl_p = entry_p - (0.90 * mid_dist)

            # Split position: 50% closes at TP1 (locks in high win rate), 50% runs to TP2 (eats losses!)
            # When TP1 is hit, SL jumps to entry + 0.01 for the runner!
            tp1_hit = False
            pnl_part1 = 0.0
            pnl_part2 = 0.0
            closed = False

            for k in range(i, min(i + 35, n)):
                # Check TP1
                if not tp1_hit and h[k] >= tp1:
                    tp1_hit = True
                    pnl_part1 = (tp1 - entry_p) * mult * 0.5
                    sl_p = entry_p + 0.01 # risk-free on runner!

                # Check SL
                if l[k] <= sl_p:
                    if not tp1_hit:
                        pnl_part1 = (sl_p - entry_p) * mult * 0.5
                    pnl_part2 = (sl_p - entry_p) * mult * 0.5
                    last_exit_idx = k
                    closed = True
                    break

                # Check TP2
                if tp1_hit and h[k] >= tp2:
                    pnl_part2 = (tp2 - entry_p) * mult * 0.5
                    last_exit_idx = k
                    closed = True
                    break
            else:
                # timed out
                exit_c = c[min(i + 35, n) - 1]
                if not tp1_hit:
                    pnl_part1 = (exit_c - entry_p) * mult * 0.5
                pnl_part2 = (exit_c - entry_p) * mult * 0.5
                last_exit_idx = min(i + 35, n) - 1

            total_pnl = pnl_part1 + pnl_part2
            trades.append({'date': df['date'].iloc[i], 'win': total_pnl > 0, 'pnl': total_pnl})

        elif short_c:
            entry_p = o[i]
            mid_dist = entry_p - mid[i-1]
            if mid_dist < 0.03:
                continue

            tp1 = mid[i-1]
            tp2 = lower[i-1]
            sl_p = entry_p + (0.90 * mid_dist)

            tp1_hit = False
            pnl_part1 = 0.0
            pnl_part2 = 0.0
            closed = False

            for k in range(i, min(i + 35, n)):
                if not tp1_hit and l[k] <= tp1:
                    tp1_hit = True
                    pnl_part1 = (entry_p - tp1) * mult * 0.5
                    sl_p = entry_p - 0.01

                if h[k] >= sl_p:
                    if not tp1_hit:
                        pnl_part1 = (entry_p - sl_p) * mult * 0.5
                    pnl_part2 = (entry_p - sl_p) * mult * 0.5
                    last_exit_idx = k
                    closed = True
                    break

                if tp1_hit and l[k] <= tp2:
                    pnl_part2 = (entry_p - tp2) * mult * 0.5
                    last_exit_idx = k
                    closed = True
                    break
            else:
                exit_c = c[min(i + 35, n) - 1]
                if not tp1_hit:
                    pnl_part1 = (entry_p - exit_c) * mult * 0.5
                pnl_part2 = (entry_p - exit_c) * mult * 0.5
                last_exit_idx = min(i + 35, n) - 1

            total_pnl = pnl_part1 + pnl_part2
            trades.append({'date': df['date'].iloc[i], 'win': total_pnl > 0, 'pnl': total_pnl})

    tdf = pd.DataFrame(trades)
    daily = tdf.groupby('date').agg(
        trades=('win', 'count'),
        wins=('win', lambda x: (x == True).sum()),
        losses=('win', lambda x: (x == False).sum()),
        dpnl=('pnl', 'sum')
    )
    g_days = (daily['dpnl'] > 0).sum()
    r_days = (daily['dpnl'] < 0).sum()
    d_wr = g_days / len(daily) * 100

    print("=" * 70)
    print("  ULTIMATE SILVER MASTERPIECE: SPLIT-TARGET MEAN REVERSION RUNNER")
    print("=" * 70)
    print(f"Total Period Analyzed     : {df['date'].min()} to {df['date'].max()} ({len(daily)} active trading days)")
    print(f"Total Trades Taken        : {len(tdf)}")
    print(f"Overall Win Rate          : {tdf['win'].mean()*100:.1f}% ({tdf['win'].sum()} Wins vs {(~tdf['win']).sum()} Losses)")
    print(f"Profit Factor             : {tdf[tdf['pnl']>0]['pnl'].sum() / abs(tdf[tdf['pnl']<0]['pnl'].sum()):.2f}")
    print(f"Total Net PnL (0.05 lot)  : +${tdf['pnl'].sum():,.2f}")
    print(f"Daily Green Day Win Rate  : {g_days} Green Days / {r_days} Red Days ({d_wr:.1f}% Green Days)")
    print(f"Avg Win Size              : +${tdf[tdf['pnl'] > 0]['pnl'].mean():.2f}")
    print(f"Avg Loss Size             : -${abs(tdf[tdf['pnl'] < 0]['pnl'].mean()):.2f}")

    print("\n" + "=" * 70)
    print("  DAY-BY-DAY PERFORMANCE BREAKDOWN:")
    print("=" * 70)
    for d, r in daily.iterrows():
        status = "GREEN" if r['dpnl'] > 0 else ("RED" if r['dpnl'] < 0 else "FLAT")
        print(f"  {d} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | Win Rate: {r['wins']/r['trades']*100:5.1f}% | PnL: ${r['dpnl']:+8.2f} [{status}]")

run_silver_split_target_mastery()
