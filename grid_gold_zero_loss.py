import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_gold_pure_sim():
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
    n = len(df)
    mult = 100.0

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # Test what produces 100% green days on Gold:
    # Gold contract size: 100 oz
    # 0.05 lot = $5.00 per point
    # 0.10 lot = $10.00 per point
    # 0.20 lot = $20.00 per point
    # On Gold, standard M1 targets are 1.20 to 3.00 points ($6 to $15 on 0.05 lot)
    for bb_dev in [2.2, 2.4, 2.5]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + bb_dev * std
        lower = mid - bb_dev * std

        for rsi_thresh in [30, 35]:
            delta = pd.Series(c).diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / (loss + 1e-9)
            rsi = (100 - (100 / (1 + rs))).values

            for lock_target in [20.0, 25.0, 30.0]:
                for sl_points in [2.50, 3.00, 3.50]:
                    daily_results = {}
                    cur_day = None
                    day_pnl = 0.0
                    day_trades = []
                    consec_losses = 0
                    locked_green = False
                    last_exit = -1

                    ladder = [0.03, 0.08, 0.18, 0.30]

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

                        idx = min(consec_losses, len(ladder) - 1)
                        cur_lot = 0.07 if (consec_losses == 0 and day_pnl < 0) else ladder[idx]

                        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_thresh) and (c[i-1] >= h1_ema50[i-1] - 3.50)
                        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 100 - rsi_thresh) and (c[i-1] <= h1_ema50[i-1] + 3.50)

                        if long_c or short_c:
                            is_long = long_c
                            entry = o[i]
                            target_pts = abs(entry - mid[i-1])
                            target_pts = max(1.20, min(3.50, target_pts))
                            tp = round(entry + target_pts, 2) if is_long else round(entry - target_pts, 2)
                            sl = round(entry - sl_points, 2) if is_long else round(entry + sl_points, 2)

                            win = False
                            pnl = 0.0
                            exit_idx = i
                            for k in range(i, min(i + 20, n)):
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
                                pnl = ((c[min(i + 20, n) - 1] - entry) if is_long else (entry - c[min(i + 20, n) - 1])) * mult * cur_lot
                                win = pnl > 0
                                exit_idx = min(i + 20, n) - 1

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
                    if green_days >= 14:
                        print(f"HIGH MATCH: {green_days}/{total_days} GREEN | bb={bb_dev}, rsi={rsi_thresh}, lock={lock_target}, sl={sl_points} | Net: ${tot_pnl:+.2f}")
                        if green_days == total_days:
                            print(">>> 100% PERFECT ZERO LOSS GOLD FOUND! <<<")
                            for d, r in sorted(daily_results.items()):
                                status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
                                print(f"  {d} | {r['trades']} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+8.2f} {status}")
                            return

if __name__ == "__main__":
    run_gold_pure_sim()
