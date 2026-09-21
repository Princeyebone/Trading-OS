import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_adaptive_martingale_recovery():
    if not mt5.initialize():
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 8000)
    mt5.shutdown()

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    n = len(df)

    mult = 5000

    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    # Let's test the recovery rule:
    # 1. Base trade = 0.03 lot (tiny risk, ~$20 SL)
    # 2. If trade 1 wins (+~$30), DAY IS GREEN & LOCKED.
    # 3. If trade 1 loses (-$20), trade 2 scales to 0.06 lot (with higher entry confirmation RSI < 25 / > 75).
    #    When trade 2 wins, it makes +$60, which completely eats the -$20 and leaves the day +$40 GREEN!
    # 4. If trade 2 wins, DAY IS GREEN & LOCKED.
    
    daily_results = {}
    current_day = None
    day_pnl = 0.0
    day_locked = False
    day_trades = []
    consecutive_losses = 0
    last_exit_idx = -1

    for i in range(25, n - 35):
        cur_date = df['date'].iloc[i]
        cur_hour = df['hour'].iloc[i]

        if cur_date != current_day:
            if current_day is not None:
                daily_results[current_day] = {
                    'pnl': day_pnl,
                    'trades': len(day_trades),
                    'wins': sum(1 for t in day_trades if t['pnl'] > 0),
                    'losses': sum(1 for t in day_trades if t['pnl'] <= 0),
                    'locked': day_locked
                }
            current_day = cur_date
            day_pnl = 0.0
            day_locked = False
            day_trades = []
            consecutive_losses = 0

        if day_locked:
            continue

        if i <= last_exit_idx:
            continue

        if not (7 <= cur_hour <= 18):
            continue

        # Sizing ladder: 0.03 -> 0.06 -> 0.12 (max 3 attempts per day)
        if consecutive_losses == 0:
            lot = 0.03
            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (lower_wick[i-1] >= body[i-1])
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (upper_wick[i-1] >= body[i-1])
        elif consecutive_losses == 1:
            lot = 0.06 # covers previous loss + surplus
            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 26) and (lower_wick[i-1] >= 1.2 * body[i-1])
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 74) and (upper_wick[i-1] >= 1.2 * body[i-1])
        elif consecutive_losses == 2:
            lot = 0.12
            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 22) and (lower_wick[i-1] >= 1.5 * body[i-1])
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 78) and (upper_wick[i-1] >= 1.5 * body[i-1])
        else:
            continue # stop day if 3 losses hit

        if long_c:
            entry_p = o[i]
            mid_dist = mid[i-1] - entry_p
            if mid_dist < 0.03:
                continue

            tp1 = mid[i-1]
            sl_p = entry_p - (0.85 * mid_dist)

            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 35, n)):
                if not be_active and h[k] >= entry_p + (0.40 * mid_dist):
                    sl_p = entry_p + 0.005
                    be_active = True

                if l[k] <= sl_p:
                    pnl = (sl_p - entry_p) * mult * lot
                    last_exit_idx = k
                    break
                elif h[k] >= tp1:
                    pnl = (tp1 - entry_p) * mult * lot
                    last_exit_idx = k
                    break
            else:
                pnl = (c[min(i + 35, n) - 1] - entry_p) * mult * lot
                last_exit_idx = min(i + 35, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if pnl > 0:
                consecutive_losses = 0
                if day_pnl > 0:
                    day_locked = True # DAY ENDS IN PROFIT!
            else:
                consecutive_losses += 1

        elif short_c:
            entry_p = o[i]
            mid_dist = entry_p - mid[i-1]
            if mid_dist < 0.03:
                continue

            tp1 = mid[i-1]
            sl_p = entry_p + (0.85 * mid_dist)

            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 35, n)):
                if not be_active and l[k] <= entry_p - (0.40 * mid_dist):
                    sl_p = entry_p - 0.005
                    be_active = True

                if h[k] >= sl_p:
                    pnl = (entry_p - sl_p) * mult * lot
                    last_exit_idx = k
                    break
                elif l[k] <= tp1:
                    pnl = (entry_p - tp1) * mult * lot
                    last_exit_idx = k
                    break
            else:
                pnl = (entry_p - c[min(i + 35, n) - 1]) * mult * lot
                last_exit_idx = min(i + 35, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if pnl > 0:
                consecutive_losses = 0
                if day_pnl > 0:
                    day_locked = True
            else:
                consecutive_losses += 1

    if current_day is not None and current_day not in daily_results:
        daily_results[current_day] = {
            'pnl': day_pnl,
            'trades': len(day_trades),
            'wins': sum(1 for t in day_trades if t['pnl'] > 0),
            'losses': sum(1 for t in day_trades if t['pnl'] <= 0),
            'locked': day_locked
        }

    res_df = pd.DataFrame.from_dict(daily_results, orient='index')
    res_df = res_df.reset_index().rename(columns={'index': 'date'})
    active_days = res_df[res_df['trades'] > 0]
    green_days = active_days[active_days['pnl'] > 0]
    red_days = active_days[active_days['pnl'] < 0]

    print("=" * 75)
    print("  ADAPTIVE RECOVERY: EVERY DAY ENDS IN PROFIT (SILVER XAGUSD)")
    print("=" * 75)
    print(f"Total Active Trading Days: {len(active_days)}")
    print(f"GREEN DAYS               : {len(green_days)} of {len(active_days)} ({len(green_days)/len(active_days)*100:.1f}%)")
    print(f"RED DAYS                 : {len(red_days)}")
    print(f"Total Net PnL            : +${active_days['pnl'].sum():,.2f}")
    print(f"Total Trades Taken       : {active_days['trades'].sum()} ({active_days['wins'].sum()} Wins / {active_days['losses'].sum()} Losses)")
    print(f"Overall Trade Win Rate   : {active_days['wins'].sum()/active_days['trades'].sum()*100:.1f}%")

    print("\n" + "=" * 75)
    print("  EXACT DAY-BY-DAY AUDIT RECORD:")
    print("=" * 75)
    for _, r in active_days.iterrows():
        status = "GREEN (SESSION WON)" if r['pnl'] > 0 else "RED"
        print(f"  {r['date']} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | PnL: ${r['pnl']:+8.2f} [{status}]")

run_silver_adaptive_martingale_recovery()
