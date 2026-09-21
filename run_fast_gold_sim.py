import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def simulate_gold(df, c, h, l, o, h1_ema50, dev, rsi_p, min_dist, tp_factor, sl_mult, lock_target, ladder):
    n = len(df)
    mult = 100.0

    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + dev * std
    lower = mid - dev * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(rsi_p).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_p).mean()
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

        if locked_green or i <= last_exit or not (6 <= cur_hour <= 19):
            continue

        if consec_losses == 0:
            cur_lot = ladder[1] if day_pnl < 0 else ladder[0]
            rsi_low, rsi_high = (32, 68) if rsi_p == 14 else (28, 72)
            cur_tp_factor = tp_factor
        elif consec_losses == 1:
            cur_lot = ladder[1]
            rsi_low, rsi_high = (28, 72) if rsi_p == 14 else (24, 76)
            cur_tp_factor = 0.55
        elif consec_losses == 2:
            cur_lot = ladder[2]
            rsi_low, rsi_high = (24, 76) if rsi_p == 14 else (20, 80)
            cur_tp_factor = 0.55
        else:
            cur_lot = ladder[3]
            rsi_low, rsi_high = (20, 80) if rsi_p == 14 else (18, 82)
            cur_tp_factor = 0.55

        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_low) and (c[i-1] >= h1_ema50[i-1] - 3.50)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_high) and (c[i-1] <= h1_ema50[i-1] + 3.50)

        if long_c:
            entry = o[i]
            dist = mid[i-1] - entry
            if dist < min_dist: continue
            tp = entry + (cur_tp_factor * dist)
            sl = entry - (sl_mult * (tp - entry))

            win = False
            pnl = 0.0
            for k in range(i, min(i + 20, n)):
                if l[k] <= sl:
                    pnl = (sl - entry) * mult * cur_lot
                    last_exit = k
                    break
                elif h[k] >= tp:
                    pnl = (tp - entry) * mult * cur_lot
                    win = True
                    last_exit = k
                    break
            else:
                pnl = (c[min(i + 20, n) - 1] - entry) * mult * cur_lot
                win = pnl > 0
                last_exit = min(i + 20, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if win:
                consec_losses = 0
                if day_pnl >= lock_target:
                    locked_green = True
            else:
                consec_losses += 1

        elif short_c:
            entry = o[i]
            dist = entry - mid[i-1]
            if dist < min_dist: continue
            tp = entry - (cur_tp_factor * dist)
            sl = entry + (sl_mult * (entry - tp))

            win = False
            pnl = 0.0
            for k in range(i, min(i + 20, n)):
                if h[k] >= sl:
                    pnl = (entry - sl) * mult * cur_lot
                    last_exit = k
                    break
                elif l[k] <= tp:
                    pnl = (entry - tp) * mult * cur_lot
                    win = True
                    last_exit = k
                    break
            else:
                pnl = (entry - c[min(i + 20, n) - 1]) * mult * cur_lot
                win = pnl > 0
                last_exit = min(i + 20, n) - 1

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
    rates_m1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 20000)
    rates_h1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 1000)
    mt5.shutdown()

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # Test fine grid
    tests = [
        # dev, rsi_p, min_dist, tp_factor, sl_mult, lock_target, ladder
        (2.4, 7, 0.60, 0.70, 1.1, 20.0, [0.03, 0.07, 0.15, 0.25]),
        (2.2, 7, 0.50, 0.65, 0.9, 15.0, [0.03, 0.07, 0.15, 0.25]),
        (2.3, 7, 0.60, 0.65, 1.0, 20.0, [0.03, 0.08, 0.16, 0.28]),
        (2.5, 7, 0.70, 0.70, 1.0, 20.0, [0.04, 0.09, 0.18, 0.30]),
        (2.2, 14, 0.60, 0.70, 1.0, 20.0, [0.03, 0.07, 0.15, 0.25]),
        (2.4, 14, 0.80, 0.70, 1.1, 20.0, [0.04, 0.09, 0.18, 0.30]),
    ]

    for dev, rsi_p, min_dist, tp_factor, sl_mult, lock_target, ladder in tests:
        res = simulate_gold(df, c, h, l, o, h1_ema50, dev, rsi_p, min_dist, tp_factor, sl_mult, lock_target, ladder)
        total = len(res)
        green = sum(1 for d, r in res.items() if r['pnl'] > 0)
        tot_pnl = sum(r['pnl'] for r in res.values())
        print(f"dev={dev}, rsi={rsi_p}, dist={min_dist}, tp={tp_factor}, sl={sl_mult}, lock={lock_target}, ladder={ladder}")
        print(f"  Result: {green}/{total} GREEN ({green/total*100:.1f}%) | Net: ${tot_pnl:+.2f}")
        for d, r in sorted(res.items()):
            if r['pnl'] <= 0:
                print(f"    RED: {d} | {r['trades']} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+8.2f}")
        print("-" * 70)

if __name__ == "__main__":
    run()
