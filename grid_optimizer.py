import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_grid():
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
    df_h1['h1_ema20'] = df_h1['close'].ewm(span=20, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema', 'h1_ema20']], on='time', direction='backward')
    h1_ema = df['h1_ema'].values
    h1_ema20 = df['h1_ema20'].values

    # Test parameter combos
    # We want 16 out of 16 days GREEN
    best_combo = None
    best_green = 0

    for dev in [2.2, 2.4, 2.5, 2.6]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + dev * std
        lower = mid - dev * std

        for rsi_period in [5, 7, 9]:
            delta = pd.Series(c).diff()
            gain = delta.clip(lower=0).rolling(rsi_period).mean()
            loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
            rs = gain / (loss + 1e-9)
            rsi = (100 - (100 / (1 + rs))).values

            for tp_ratio in [0.60, 0.70, 0.80]:
                for sl_ratio in [0.8, 1.0, 1.2]:
                    for lock_target in [15.0, 20.0, 25.0, 30.0]:
                        for ladder in [
                            [0.02, 0.05, 0.10, 0.18],
                            [0.02, 0.05, 0.12, 0.25],
                            [0.03, 0.07, 0.15, 0.25],
                            [0.02, 0.04, 0.08, 0.16]
                        ]:
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
                                        daily_results[cur_day] = day_pnl
                                    cur_day = cur_date
                                    day_pnl = 0.0
                                    day_trades = []
                                    consec_losses = 0
                                    locked_green = False

                                if locked_green or i <= last_exit or not (7 <= cur_hour <= 18):
                                    continue

                                idx = min(consec_losses, len(ladder) - 1)
                                cur_lot = ladder[idx]
                                rsi_thresh = 28 - (consec_losses * 2)

                                # Check alignment with H1 EMA
                                long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_thresh) and (c[i-1] >= h1_ema[i-1] - 0.20)
                                short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 100 - rsi_thresh) and (c[i-1] <= h1_ema[i-1] + 0.20)

                                if long_c:
                                    entry = o[i]
                                    dist = mid[i-1] - entry
                                    if dist < 0.025: continue
                                    tp = entry + (tp_ratio * dist)
                                    sl = entry - (sl_ratio * (tp - entry))
                                    pnl = 0.0
                                    win = False
                                    for k in range(i, min(i + 20, n)):
                                        if l[k] <= sl:
                                            pnl = (sl - entry) * mult * cur_lot
                                            last_exit = k; break
                                        elif h[k] >= tp:
                                            pnl = (tp - entry) * mult * cur_lot
                                            win = True; last_exit = k; break
                                    else:
                                        pnl = (c[min(i + 20, n) - 1] - entry) * mult * cur_lot
                                        win = pnl > 0
                                        last_exit = min(i + 20, n) - 1
                                    
                                    day_pnl += pnl
                                    day_trades.append(pnl)
                                    if win:
                                        consec_losses = 0
                                        if day_pnl >= lock_target: locked_green = True
                                    else:
                                        consec_losses += 1

                                elif short_c:
                                    entry = o[i]
                                    dist = entry - mid[i-1]
                                    if dist < 0.025: continue
                                    tp = entry - (tp_ratio * dist)
                                    sl = entry + (sl_ratio * (entry - tp))
                                    pnl = 0.0
                                    win = False
                                    for k in range(i, min(i + 20, n)):
                                        if h[k] >= sl:
                                            pnl = (entry - sl) * mult * cur_lot
                                            last_exit = k; break
                                        elif l[k] <= tp:
                                            pnl = (entry - tp) * mult * cur_lot
                                            win = True; last_exit = k; break
                                    else:
                                        pnl = (entry - c[min(i + 20, n) - 1]) * mult * cur_lot
                                        win = pnl > 0
                                        last_exit = min(i + 20, n) - 1
                                    
                                    day_pnl += pnl
                                    day_trades.append(pnl)
                                    if win:
                                        consec_losses = 0
                                        if day_pnl >= lock_target: locked_green = True
                                    else:
                                        consec_losses += 1

                            if cur_day is not None and len(day_trades) > 0 and cur_day not in daily_results:
                                daily_results[cur_day] = day_pnl

                            total_days = len(daily_results)
                            green_days = sum(1 for p in daily_results.values() if p > 0)
                            tot_pnl = sum(daily_results.values())
                            if green_days > best_green:
                                best_green = green_days
                                print(f"NEW BEST: {green_days}/{total_days} GREEN ({green_days/total_days*100:.1f}%) | Net PnL: ${tot_pnl:+.2f} | dev={dev}, rsi={rsi_period}, tp_r={tp_ratio}, sl_r={sl_ratio}, lock={lock_target}, ladder={ladder}")
                            if green_days == total_days:
                                print(f"*** 100% GREEN FOUND! ***")
                                print(f"Params: dev={dev}, rsi={rsi_period}, tp_r={tp_ratio}, sl_r={sl_ratio}, lock={lock_target}, ladder={ladder}")
                                return

if __name__ == "__main__":
    run_grid()
