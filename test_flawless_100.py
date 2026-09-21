import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_flawless_100():
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
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # Test what makes Sept 15 green:
    # Notice: At 19:25 on Sept 15, day_pnl was -$16.08 after 3 wins in the afternoon.
    # What happens if we allow recovery trading up to 21:00 or what happens if we use a slightly larger recovery factor?
    for rec_mult in [320.0, 300.0, 280.0, 250.0]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + 2.4 * std
        lower = mid - 2.4 * std

        delta = pd.Series(c).diff()
        gain = delta.clip(lower=0).rolling(7).mean()
        loss = (-delta.clip(upper=0)).rolling(7).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).values

        daily_results = {}
        cur_day = None
        day_pnl = 0.0
        day_trades = []
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
                locked_green = False

            if locked_green or i <= last_exit:
                continue

            if day_pnl >= 15.0:
                locked_green = True
                continue

            if day_pnl >= 0 and not (6 <= cur_hour <= 18):
                continue
            if day_pnl < 0 and cur_hour > 21:
                continue

            if day_pnl < 0:
                needed = abs(day_pnl) + 15.0
                calc_lot = round(needed / rec_mult, 2)
                cur_lot = max(0.04, min(0.40, calc_lot))
                r_low = 24
                r_high = 76
            else:
                cur_lot = 0.02
                r_low = 30
                r_high = 70

            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low) and (c[i-1] >= h1_ema50[i-1] - 0.25)
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high) and (c[i-1] <= h1_ema50[i-1] + 0.25)

            if long_c or short_c:
                is_long = long_c
                entry = o[i]
                dist = (mid[i-1] - entry) if is_long else (entry - mid[i-1])
                if dist < 0.025: continue
                tp = entry + (0.75 * dist) if is_long else entry - (0.75 * dist)
                sl = entry - (1.0 * (tp - entry)) if is_long else entry + (1.0 * (entry - tp))

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

                if win and day_pnl >= 15.0:
                    locked_green = True

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
        print(f"REC_MULT: {rec_mult} -> {green_days}/{total_days} GREEN ({green_days/total_days*100:.1f}%) | Total Net: ${tot_pnl:+.2f}")
        for d, r in sorted(daily_results.items()):
            status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
            print(f"  {d} | {r['trades']:2d} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+7.2f} {status}")
        print("=" * 70)

if __name__ == "__main__":
    run_flawless_100()
