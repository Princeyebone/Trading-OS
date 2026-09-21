import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_zero_loss_master():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    rates_m1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 15000)
    rates_h1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 1000)
    mt5.shutdown()

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    n = len(df)
    mult = 5000

    # H1 Trend
    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema']], on='time', direction='backward')
    h1_ema = df['h1_ema'].values

    # M1 Indicators
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.4 * std
    lower = mid - 2.4 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    # Pre-compute trades on candidate signals
    # We test two strategies:
    # 1. Base recovery sizing: 0.02 base lot -> scales to 0.05 on loss
    # 2. Daily profit stop: Once day reaches +$20 or +$30 profit, STOP & LOCK!
    
    for target_lock in [15.0, 25.0, 35.0]:
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

            # Recovery Lot Sizing:
            if consec_losses == 0:
                cur_lot = 0.02
                rsi_low, rsi_high = 30, 70
            elif consec_losses == 1:
                cur_lot = 0.05 # recovers previous loss + secures profit
                rsi_low, rsi_high = 25, 75
            else:
                cur_lot = 0.10
                rsi_low, rsi_high = 20, 80

            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_low) and (c[i-1] >= h1_ema[i-1] - 0.25)
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_high) and (c[i-1] <= h1_ema[i-1] + 0.25)

            if long_c:
                entry = o[i]
                dist = mid[i-1] - entry
                if dist < 0.025:
                    continue
                tp = entry + (0.75 * dist)
                sl = entry - (1.2 * (tp - entry)) # tight SL

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
                    if day_pnl >= target_lock:
                        locked_green = True
                else:
                    consec_losses += 1

            elif short_c:
                entry = o[i]
                dist = entry - mid[i-1]
                if dist < 0.025:
                    continue
                tp = entry - (0.75 * dist)
                sl = entry + (1.2 * (entry - tp))

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
                    if day_pnl >= target_lock:
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

        res_df = pd.DataFrame.from_dict(daily_results, orient='index').reset_index().rename(columns={'index': 'date'})
        active = res_df[res_df['trades'] > 0]
        g = (active['pnl'] > 0).sum()
        r = (active['pnl'] < 0).sum()
        tot = len(active)
        print(f"\nTarget Lock = ${target_lock:.2f} | Total Active Days: {tot} | GREEN DAYS: {g} ({g/tot*100:.1f}%) | RED DAYS: {r} | Net PnL: +${active['pnl'].sum():,.2f}")
        for _, row in active.iterrows():
            st = "GREEN" if row['pnl'] > 0 else "RED"
            print(f"  {row['date']} | Trades: {int(row['trades']):2} ({int(row['wins']):2}W / {int(row['losses']):2}L) | PnL: ${row['pnl']:+8.2f} [{st}]")

run_silver_zero_loss_master()
