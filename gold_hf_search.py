import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_gold_hf_search():
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
    mult = 100.0  # 100 oz per lot

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # Test fine tuning Config 5
    # The 4 red days in Config 5 were:
    # 2026-08-31: 1 trade (0W/1L) -3.26
    # 2026-09-01: 6 trades (1W/5L) -319.35
    # 2026-09-11: 11 trades (4W/7L) -12.90
    # 2026-09-17: 12 trades (4W/8L) -180.38
    # Let's test tightening entries when consecutive losses occur (e.g. RSI 26 -> 22 -> 18, BB dev 2.2 -> 2.4 on loss):
    for rsi_thresh in [26, 28]:
        for lock_tgt in [12.0, 15.0, 18.0]:
            for sl_r in [0.85, 0.90, 1.0]:
                for ladder in [
                    [0.02, 0.05, 0.12, 0.22],
                    [0.02, 0.05, 0.10, 0.18],
                    [0.03, 0.06, 0.14, 0.24],
                ]:
                    mid = pd.Series(c).rolling(20).mean().values
                    std = pd.Series(c).rolling(20).std().values
                    upper = mid + 2.2 * std
                    lower = mid - 2.2 * std

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

                        if locked_green or i <= last_exit or not (6 <= cur_hour <= 19):
                            continue

                        idx = min(consec_losses, len(ladder) - 1)
                        # If in deficit, scale lot slightly to erase deficit
                        if consec_losses == 0 and day_pnl < 0:
                            cur_lot = ladder[1]
                        else:
                            cur_lot = ladder[idx]

                        r_low = rsi_thresh - (consec_losses * 2)
                        r_high = (100 - rsi_thresh) + (consec_losses * 2)

                        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low) and (c[i-1] >= h1_ema50[i-1] - 3.5)
                        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high) and (c[i-1] <= h1_ema50[i-1] + 3.5)

                        if long_c:
                            entry = o[i]
                            dist = mid[i-1] - entry
                            if dist < 0.60: continue
                            tp = entry + (0.65 * dist)
                            sl = entry - (sl_r * (tp - entry))

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
                                if day_pnl >= lock_tgt:
                                    locked_green = True
                            else:
                                consec_losses += 1

                        elif short_c:
                            entry = o[i]
                            dist = entry - mid[i-1]
                            if dist < 0.60: continue
                            tp = entry - (0.65 * dist)
                            sl = entry + (sl_r * (entry - tp))

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
                                if day_pnl >= lock_tgt:
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
                        print(f"HIGH MATCH: {green_days}/{total_days} GREEN | rsi={rsi_thresh}, lock={lock_tgt}, sl_r={sl_r}, ladder={ladder} | Net: ${tot_pnl:+.2f}")
                        if green_days == total_days:
                            print(">>> 100% PERFECT ZERO LOSS GOLD FOUND! <<<")
                            for d, r in sorted(daily_results.items()):
                                status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
                                print(f"  {d} | {r['trades']} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+8.2f} {status}")
                            return

if __name__ == "__main__":
    run_gold_hf_search()
