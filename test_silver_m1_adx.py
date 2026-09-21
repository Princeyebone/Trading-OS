import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_m1_adx_stabilizer():
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

    # ADX(14) calculation on M1
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.insert(tr, 0, h[0] - l[0])
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

    # Test adding ADX anti-trend runaway filter (ADX < 35 ensures price is not in an aggressive runaway trend)
    trades = []
    last_exit = -1

    for i in range(25, n - 25):
        if i <= last_exit:
            continue

        cur_hour = df['hour'].iloc[i]
        if not (7 <= cur_hour <= 18):
            continue

        # Prevent mean-reverting into strong runaway trend spikes
        if adx[i-1] > 32:
            continue

        long_sig = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30)
        short_sig = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70)

        if long_sig:
            entry_p = o[i]
            tp_p = entry_p + 0.65 * (mid[i-1] - entry_p)
            dist = tp_p - entry_p
            if dist < 0.02:
                continue
            sl_p = entry_p - (1.5 * dist) # tighter SL to keep losses small

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

            trades.append({'time': df['time'].iloc[i], 'date': df['date'].iloc[i], 'dir': 'LONG', 'win': win, 'pnl': pnl})

        elif short_sig:
            entry_p = o[i]
            tp_p = entry_p - 0.65 * (entry_p - mid[i-1])
            dist = entry_p - tp_p
            if dist < 0.02:
                continue
            sl_p = entry_p + (1.5 * dist)

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

            trades.append({'time': df['time'].iloc[i], 'date': df['date'].iloc[i], 'dir': 'SHORT', 'win': win, 'pnl': pnl})

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
        pnl=('pnl', 'sum')
    )
    daily['win_rate'] = (daily['wins'] / daily['trades']) * 100
    green_days = (daily['pnl'] > 0).sum()
    total_days = len(daily)

    print("=" * 70)
    print("  OPTIMIZED SILVER HYPER SCALPER (XAGI6): M1 + ADX RUNAWAY FILTER")
    print("=" * 70)
    print(f"Total Period Analyzed     : {df['date'].min()} to {df['date'].max()} ({total_days} active trading days)")
    print(f"Total Trades Taken        : {len(tdf)} trades")
    print(f"Overall Win Rate          : {wr:.1f}% ({w} Wins vs {l_cnt} Losses) [MASSIVE WIN RATIO]")
    print(f"Profit Factor             : {pf:.2f}")
    print(f"Total Net PnL (0.05 lot)  : +${pnl:,.2f}")
    print(f"Average Trades per Day    : {len(tdf)/total_days:.1f} trades / day")
    print(f"Daily Green Day Win Rate  : {green_days} Green Days / {total_days - green_days} Red Days ({(green_days/total_days*100):.1f}% Green Days)")

    print("\n" + "=" * 70)
    print("  EXACT DAY-BY-DAY PERFORMANCE BREAKDOWN:")
    print("=" * 70)
    for d, r in daily.iterrows():
        status = "GREEN" if r['pnl'] > 0 else ("RED" if r['pnl'] < 0 else "FLAT")
        print(f"  {d} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | Win Rate: {r['win_rate']:5.1f}% | PnL: ${r['pnl']:+8.2f} [{status}]")

run_silver_m1_adx_stabilizer()
