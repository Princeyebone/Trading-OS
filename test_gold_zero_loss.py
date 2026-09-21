import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_gold_audit():
    if not mt5.initialize():
        print("MT5 init failed")
        return

    # Gold XAUUSD contract: 100 oz ($10 per $1.00 move per 0.10 lot, or $1.00 per pt on 0.01 lot, $5.00 per pt on 0.05 lot)
    rates_m1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 20000)
    rates_h1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, 1000)
    mt5.shutdown()

    if rates_m1 is None or rates_h1 is None:
        print("Failed to fetch rates")
        return

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    n = len(df)
    mult = 100.0  # 100 oz contract size

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # BB (20, 2.4) and RSI (7)
    bb_dev = 2.4
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + bb_dev * std
    lower = mid - bb_dev * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    # Test parameters for Gold
    # On Gold, average M1 BB half-width is around 1.50 to 3.50 points.
    # On 0.02 lot, a 2.0 pt move = $4.00. On 0.05 lot = $10.00. On 0.12 lot = $24.00.
    for lock_target in [20.0, 25.0, 30.0]:
        for base_lot, rec_lot_1, rec_lot_2, rec_lot_3 in [
            (0.02, 0.05, 0.12, 0.20),
            (0.03, 0.07, 0.15, 0.25),
            (0.02, 0.06, 0.14, 0.22),
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
                    cur_lot = (base_lot * 2.5) if day_pnl < 0 else base_lot
                    rsi_low, rsi_high = 30, 70
                    tp_factor = 0.70
                elif consec_losses == 1:
                    cur_lot = rec_lot_1
                    rsi_low, rsi_high = 25, 75
                    tp_factor = 0.55
                elif consec_losses == 2:
                    cur_lot = rec_lot_2
                    rsi_low, rsi_high = 20, 80
                    tp_factor = 0.55
                else:
                    cur_lot = rec_lot_3
                    rsi_low, rsi_high = 18, 82
                    tp_factor = 0.55

                # On Gold, EMA distance tolerance is ~3.0 points
                long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_low) and (c[i-1] >= h1_ema50[i-1] - 3.0)
                short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_high) and (c[i-1] <= h1_ema50[i-1] + 3.0)

                if long_c:
                    entry = o[i]
                    dist = mid[i-1] - entry
                    if dist < 0.60: # Min 6 pips on Gold
                        continue
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
                        if day_pnl >= lock_target:
                            locked_green = True
                    else:
                        consec_losses += 1

                elif short_c:
                    entry = o[i]
                    dist = entry - mid[i-1]
                    if dist < 0.60:
                        continue
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
            print(f"Lock: {lock_target} | Ladder: [{base_lot}, {rec_lot_1}, {rec_lot_2}, {rec_lot_3}]")
            print(f"  Result: {green_days}/{total_days} GREEN ({green_days/total_days*100:.1f}%) | Net: ${tot_pnl:+.2f}")
            for d, r in sorted(daily_results.items()):
                status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
                print(f"    {d} | {r['trades']:2d} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+8.2f} {status}")
            print("=" * 70)

if __name__ == "__main__":
    run_gold_audit()
