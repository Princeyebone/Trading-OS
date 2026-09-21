import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_super_edge():
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
    mult = 5000

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema']], on='time', direction='backward')
    h1_ema = df['h1_ema'].values

    # Test adding ADX / ATR trend filter + Session Locking
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.5 * std
    lower = mid - 2.5 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    # Test with varying lock targets and ladder
    for lock_target in [10.0, 15.0, 20.0, 25.0]:
        for sl_mult in [0.75, 0.85, 1.0]:
            daily_results = {}
            cur_day = None
            day_pnl = 0.0
            day_trades = []
            consec_losses = 0
            locked_green = False
            last_exit = -1

            for i in range(25, n - 20):
                cur_date = df['date'].iloc[i]
                cur_hour = df['hour'].iloc[i]

                if cur_date != cur_day:
                    if cur_day is not None and len(day_trades) > 0:
                        daily_results[cur_day] = {
                            'pnl': day_pnl,
                            'trades': len(day_trades),
                            'wins': sum(1 for t in day_trades if t['pnl'] > 0),
                            'losses': sum(1 for t in day_trades if t['pnl'] <= 0)
                        }
                    cur_day = cur_date
                    day_pnl = 0.0
                    day_trades = []
                    consec_losses = 0
                    locked_green = False

                if locked_green or i <= last_exit or not (7 <= cur_hour <= 19):
                    continue

                # Adaptive recovery lot
                if day_pnl < 0:
                    needed = abs(day_pnl) + 12.0
                    # Aim to wipe out the deficit in 1 win (average win is ~0.08 pts = $400/lot)
                    cur_lot = round(min(0.25, max(0.04, needed / 350.0)), 2)
                else:
                    cur_lot = 0.02

                # Extreme filter
                r_low = 26 - (consec_losses * 2)
                r_high = 74 + (consec_losses * 2)

                long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low) and (c[i-1] >= h1_ema[i-1] - 0.25)
                short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high) and (c[i-1] <= h1_ema[i-1] + 0.25)

                if long_c or short_c:
                    is_long = long_c
                    entry = o[i]
                    dist = (mid[i-1] - entry) if is_long else (entry - mid[i-1])
                    if dist < 0.025: continue
                    tp = entry + (0.75 * dist) if is_long else entry - (0.75 * dist)
                    sl = entry - (sl_mult * (tp - entry)) if is_long else entry + (sl_mult * (entry - tp))

                    win = False
                    pnl = 0.0
                    exit_idx = i
                    for k in range(i, min(i + 25, n)):
                        if is_long:
                            if l[k] <= sl:
                                pnl = (sl - entry) * mult * cur_lot
                                exit_idx = k; break
                            elif h[k] >= tp:
                                pnl = (tp - entry) * mult * cur_lot
                                win = True; exit_idx = k; break
                        else:
                            if h[k] >= sl:
                                pnl = (entry - sl) * mult * cur_lot
                                exit_idx = k; break
                            elif l[k] <= tp:
                                pnl = (entry - tp) * mult * cur_lot
                                win = True; exit_idx = k; break
                    else:
                        pnl = ((c[min(i + 25, n) - 1] - entry) if is_long else (entry - c[min(i + 25, n) - 1])) * mult * cur_lot
                        win = pnl > 0
                        exit_idx = min(i + 25, n) - 1

                    last_exit = exit_idx
                    day_pnl += pnl
                    day_trades.append({'pnl': pnl})

                    if win:
                        consec_losses = 0
                        if day_pnl >= lock_target:
                            locked_green = True
                    else:
                        consec_losses += 1

            if cur_day is not None and len(day_trades) > 0 and cur_day not in daily_results:
                daily_results[cur_day] = {
                    'pnl': day_pnl,
                    'trades': len(day_trades),
                    'wins': sum(1 for t in day_trades if t['pnl'] > 0),
                    'losses': sum(1 for t in day_trades if t['pnl'] <= 0)
                }

            total_days = len(daily_results)
            green_days = sum(1 for d, r in daily_results.items() if r['pnl'] > 0)
            tot_pnl = sum(r['pnl'] for r in daily_results.values())
            if green_days >= 15:
                print(f"HIGH MATCH: {green_days}/{total_days} GREEN | lock={lock_target}, sl_mult={sl_mult} | Total Net: ${tot_pnl:+.2f}")
                for d, r in sorted(daily_results.items()):
                    status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
                    print(f"    {d} | {r['trades']:2d} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+7.2f} {status}")
                print("*" * 80)

if __name__ == "__main__":
    run_silver_super_edge()
