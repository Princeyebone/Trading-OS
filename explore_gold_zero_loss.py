import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def explore_gold_zero_loss():
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
    mult = 100.0  # 100 oz per lot ($100 per $1.00 move per 1.0 lot; $5.00 per pt per 0.05 lot)

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df_h1['h1_ema20'] = df_h1['close'].ewm(span=20, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50', 'h1_ema20']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # Test parameter grid on Gold
    configs = [
        # (bb_dev, rsi_p, rsi_low, tp_ratio, sl_ratio, lock_tgt, ladder)
        ("Gold Standard: BB 2.5, RSI 14, TP 0.85, SL 1.1, Ladder [0.03, 0.07, 0.16, 0.28]", 2.5, 14, 32, 0.85, 1.1, 20.0, [0.03, 0.07, 0.16, 0.28]),
        ("Gold Fast-RSI: BB 2.6, RSI 7, TP 0.75, SL 1.0, Ladder [0.03, 0.08, 0.18, 0.30]", 2.6, 7, 26, 0.75, 1.0, 20.0, [0.03, 0.08, 0.18, 0.30]),
        ("Gold Strict-Trend: BB 2.4, RSI 14, TP 0.70, SL 0.95, Ladder [0.04, 0.09, 0.20, 0.35]", 2.4, 14, 30, 0.70, 0.95, 25.0, [0.04, 0.09, 0.20, 0.35]),
        ("Gold Adaptive Recovery: BB 2.5, RSI 7, TP 0.80, SL 1.0, Ladder [0.03, 0.07, 0.15, 0.25]", 2.5, 7, 25, 0.80, 1.0, 20.0, [0.03, 0.07, 0.15, 0.25]),
        ("Gold High-Frequency: BB 2.2, RSI 7, TP 0.65, SL 0.90, Ladder [0.02, 0.05, 0.12, 0.22]", 2.2, 7, 28, 0.65, 0.90, 15.0, [0.02, 0.05, 0.12, 0.22]),
    ]

    for label, bb_dev, rsi_p, rsi_bound, tp_r, sl_r, lock_tgt, ladder in configs:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + bb_dev * std
        lower = mid - bb_dev * std

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

            # Ladder
            idx = min(consec_losses, len(ladder) - 1)
            # If consec_losses is 0 but day_pnl < 0, use step 1 to recover deficit
            if consec_losses == 0 and day_pnl < 0:
                cur_lot = ladder[1]
            else:
                cur_lot = ladder[idx]

            r_low = rsi_bound - (consec_losses * 2)
            r_high = (100 - rsi_bound) + (consec_losses * 2)

            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low) and (c[i-1] >= h1_ema50[i-1] - 4.0)
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high) and (c[i-1] <= h1_ema50[i-1] + 4.0)

            if long_c:
                entry = o[i]
                dist = mid[i-1] - entry
                if dist < 0.80: continue
                tp = entry + (tp_r * dist)
                sl = entry - (sl_r * (tp - entry))

                win = False
                pnl = 0.0
                for k in range(i, min(i + 25, n)):
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
                    pnl = (c[min(i + 25, n) - 1] - entry) * mult * cur_lot
                    win = pnl > 0
                    last_exit = min(i + 25, n) - 1

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
                if dist < 0.80: continue
                tp = entry - (tp_r * dist)
                sl = entry + (sl_r * (entry - tp))

                win = False
                pnl = 0.0
                for k in range(i, min(i + 25, n)):
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
                    pnl = (entry - c[min(i + 25, n) - 1]) * mult * cur_lot
                    win = pnl > 0
                    last_exit = min(i + 25, n) - 1

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
        print(f"CONFIG: {label}")
        print(f"  Result: {green_days}/{total_days} GREEN ({green_days/total_days*100:.1f}%) | Net: ${tot_pnl:+.2f}")
        for d, r in sorted(daily_results.items()):
            status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
            print(f"    {d} | {r['trades']:2d} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+8.2f} {status}")
        print("=" * 70)

if __name__ == "__main__":
    explore_gold_zero_loss()
