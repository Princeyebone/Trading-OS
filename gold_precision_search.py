import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_gold_precision_search():
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
    mult = 100.0  # 100 oz per lot ($100 per $1.00 move per 1.0 lot)

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df_h1['h1_ema20'] = df_h1['close'].ewm(span=20, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50', 'h1_ema20']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values
    h1_ema20 = df['h1_ema20'].values

    # Test exact combinations
    # Ladder: 0.03 base -> 0.08 on deficit/loss 1 -> 0.16 on loss 2 -> 0.28 on loss 3
    # Target: 0.70x to mid-band (or 0.55x in recovery)
    for ema_filter in ['h1_ema50', 'h1_ema20']:
        ema_vals = h1_ema50 if ema_filter == 'h1_ema50' else h1_ema20
        for dev in [2.2, 2.4, 2.5]:
            mid = pd.Series(c).rolling(20).mean().values
            std = pd.Series(c).rolling(20).std().values
            upper = mid + dev * std
            lower = mid - dev * std

            for rsi_period in [7, 14]:
                delta = pd.Series(c).diff()
                gain = delta.clip(lower=0).rolling(rsi_period).mean()
                loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
                rs = gain / (loss + 1e-9)
                rsi = (100 - (100 / (1 + rs))).values

                for lock_pnl in [15.0, 20.0, 25.0]:
                    daily_results = {}
                    cur_day = None
                    day_pnl = 0.0
                    day_trades = []
                    consec_losses = 0
                    locked_green = False
                    last_exit = -1

                    ladder = [0.03, 0.08, 0.16, 0.28]

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

                        # Adaptive recovery lot:
                        if consec_losses == 0:
                            cur_lot = 0.07 if day_pnl < 0 else 0.03
                            rsi_low = 32 if rsi_period == 14 else 28
                            rsi_high = 68 if rsi_period == 14 else 72
                            tp_factor = 0.70
                        elif consec_losses == 1:
                            cur_lot = 0.08
                            rsi_low = 28 if rsi_period == 14 else 24
                            rsi_high = 72 if rsi_period == 14 else 76
                            tp_factor = 0.55
                        elif consec_losses == 2:
                            cur_lot = 0.16
                            rsi_low = 25 if rsi_period == 14 else 20
                            rsi_high = 75 if rsi_period == 14 else 80
                            tp_factor = 0.55
                        else:
                            cur_lot = 0.28
                            rsi_low = 22 if rsi_period == 14 else 18
                            rsi_high = 78 if rsi_period == 14 else 82
                            tp_factor = 0.55

                        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_low) and (c[i-1] >= ema_vals[i-1] - 2.50)
                        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_high) and (c[i-1] <= ema_vals[i-1] + 2.50)

                        if long_c:
                            entry = o[i]
                            dist = mid[i-1] - entry
                            if dist < 0.60: continue
                            tp = entry + (tp_factor * dist)
                            sl = entry - (1.1 * (tp - entry))

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
                                if day_pnl >= lock_pnl:
                                    locked_green = True
                            else:
                                consec_losses += 1

                        elif short_c:
                            entry = o[i]
                            dist = entry - mid[i-1]
                            if dist < 0.60: continue
                            tp = entry - (tp_factor * dist)
                            sl = entry + (1.1 * (entry - tp))

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
                                if day_pnl >= lock_pnl:
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
                        print(f"HIGH MATCH: {green_days}/{total_days} GREEN | ema={ema_filter}, bb={dev}, rsi_p={rsi_period}, lock={lock_pnl} | Net: ${tot_pnl:+.2f}")
                        if green_days == total_days:
                            print(">>> 100% PERFECT ZERO LOSS GOLD FOUND! <<<")
                            for d, r in sorted(daily_results.items()):
                                status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
                                print(f"  {d} | {r['trades']} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+8.2f} {status}")
                            return

if __name__ == "__main__":
    run_gold_precision_search()
