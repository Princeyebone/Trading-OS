import MetaTrader5 as mt5
import pandas as pd

def inspect_sept15():
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

    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.4 * std
    lower = mid - 2.4 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    cur_day = None
    day_pnl = 0.0
    consec_losses = 0
    locked_green = False
    last_exit = -1

    for i in range(25, n - 20):
        cur_date = df['date'].iloc[i]
        cur_hour = df['hour'].iloc[i]

        if cur_date != cur_day:
            cur_day = cur_date
            day_pnl = 0.0
            consec_losses = 0
            locked_green = False

        if locked_green or i <= last_exit or not (6 <= cur_hour <= 20):
            continue

        if day_pnl < 0:
            needed_profit = abs(day_pnl) + 15.0
            target_lot = round(needed_profit / 500.0, 2)
            cur_lot = max(0.04, min(0.30, target_lot))
        else:
            cur_lot = 0.02

        rsi_low = 30 - (consec_losses * 2)
        rsi_high = 70 + (consec_losses * 2)

        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_low) and (c[i-1] >= h1_ema[i-1] - 0.25)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_high) and (c[i-1] <= h1_ema[i-1] + 0.25)

        if long_c or short_c:
            is_long = long_c
            entry = o[i]
            dist = (mid[i-1] - entry) if is_long else (entry - mid[i-1])
            if dist < 0.025:
                continue
            tp = entry + (0.75 * dist) if is_long else entry - (0.75 * dist)
            sl = entry - (1.1 * (tp - entry)) if is_long else entry + (1.1 * (entry - tp))

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
            prev_pnl = day_pnl
            day_pnl += pnl

            if cur_date == pd.to_datetime('2026-09-15').date():
                t_str = df['time'].iloc[i].strftime('%H:%M')
                side = "BUY" if is_long else "SELL"
                res = "WIN" if win else "LOSS"
                print(f"{t_str} | {side} lot={cur_lot:.2f} | entry={entry:.3f} tp={tp:.3f} sl={sl:.3f} | pnl=${pnl:+.2f} ({res}) | day_pnl=${day_pnl:+.2f}")

            if win:
                consec_losses = 0
                if day_pnl >= 15.0:
                    locked_green = True
            else:
                consec_losses += 1

if __name__ == "__main__":
    inspect_sept15()
