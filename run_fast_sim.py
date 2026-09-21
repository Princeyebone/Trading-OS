import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def fast_simulation(df, c, h, l, o, h1_ema, mult, bb_dev, rsi_thresh, tp_ratio, sl_ratio, lock_target, ladder):
    n = len(df)
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + bb_dev * std
    lower = mid - bb_dev * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

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

        if locked_green or i <= last_exit or not (6 <= cur_hour <= 20):
            continue

        idx = min(consec_losses, len(ladder) - 1)
        cur_lot = ladder[idx]
        r_low = rsi_thresh - (consec_losses * 2)
        r_high = (100 - rsi_thresh) + (consec_losses * 2)

        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low) and (c[i-1] >= h1_ema[i-1] - 0.25)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high) and (c[i-1] <= h1_ema[i-1] + 0.25)

        if long_c or short_c:
            is_long = long_c
            entry = o[i]
            dist = (mid[i-1] - entry) if is_long else (entry - mid[i-1])
            if dist < 0.025: continue
            tp = entry + (tp_ratio * dist) if is_long else entry - (tp_ratio * dist)
            sl = entry - (sl_ratio * (tp - entry)) if is_long else entry + (sl_ratio * (entry - tp))

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

    return daily_results

def run():
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
    mult = 5000

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema']], on='time', direction='backward')
    h1_ema = df['h1_ema'].values

    # Test focused variations
    test_cases = [
        # (bb_dev, rsi_thresh, tp_ratio, sl_ratio, lock_target, ladder)
        (2.4, 28, 0.75, 1.1, 20.0, [0.02, 0.05, 0.12, 0.25]),
        (2.4, 30, 0.70, 1.0, 15.0, [0.02, 0.05, 0.12, 0.22]),
        (2.5, 27, 0.75, 1.0, 20.0, [0.03, 0.07, 0.15, 0.25]),
        (2.3, 30, 0.75, 1.2, 25.0, [0.02, 0.05, 0.10, 0.20]),
        (2.4, 28, 0.80, 1.0, 20.0, [0.02, 0.06, 0.14, 0.25]),
        (2.5, 25, 0.70, 0.9, 15.0, [0.03, 0.08, 0.18, 0.30]),
    ]

    for bb_dev, rsi_thresh, tp_ratio, sl_ratio, lock_target, ladder in test_cases:
        res = fast_simulation(df, c, h, l, o, h1_ema, mult, bb_dev, rsi_thresh, tp_ratio, sl_ratio, lock_target, ladder)
        total_days = len(res)
        green_days = sum(1 for d, r in res.items() if r['pnl'] > 0)
        tot_pnl = sum(r['pnl'] for r in res.values())
        print(f"dev={bb_dev} | rsi={rsi_thresh} | tp={tp_ratio} | sl={sl_ratio} | lock={lock_target} | ladder={ladder}")
        print(f"  Result: {green_days}/{total_days} GREEN ({green_days/total_days*100:.1f}%) | Total Net: ${tot_pnl:+.2f}")
        for d, r in sorted(res.items()):
            if r['pnl'] <= 0:
                print(f"    RED: {d} | {r['trades']} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+.2f}")
        print("-" * 60)

if __name__ == "__main__":
    run()
