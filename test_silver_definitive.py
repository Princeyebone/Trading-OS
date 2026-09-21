import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_daily_master_session():
    if not mt5.initialize():
        return

    rates_m5 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 7000)
    rates_h1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 1000)
    mt5.shutdown()

    df = pd.DataFrame(rates_m5)
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

    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.2 * std
    lower = mid - 2.2 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    daily_results = {}
    current_day = None
    day_pnl = 0.0
    day_trades = []
    deficit = 0.0
    locked_green = False
    last_exit_idx = -1

    for i in range(25, n - 25):
        cur_date = df['date'].iloc[i]
        cur_hour = df['hour'].iloc[i]

        if cur_date != current_day:
            if current_day is not None:
                daily_results[current_day] = {
                    'pnl': day_pnl,
                    'trades': len(day_trades),
                    'wins': sum(1 for t in day_trades if t['pnl'] > 0),
                    'losses': sum(1 for t in day_trades if t['pnl'] <= 0),
                }
            current_day = cur_date
            day_pnl = 0.0
            day_trades = []
            deficit = 0.0
            locked_green = False

        if locked_green or i <= last_exit_idx or not (7 <= cur_hour <= 18):
            continue

        # If in deficit, we take the next ultra-clean setup
        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (lower_wick[i-1] >= body[i-1]) and (c[i-1] >= h1_ema50[i-1])
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (upper_wick[i-1] >= body[i-1]) and (c[i-1] <= h1_ema50[i-1])

        # If in deficit, also allow secondary high-probability pullback to recover
        if deficit > 0 and not (long_c or short_c):
            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 26) and (lower_wick[i-1] >= body[i-1])
            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 74) and (upper_wick[i-1] >= body[i-1])

        if long_c:
            entry_p = o[i]
            target_p = mid[i-1]
            target_dist = target_p - entry_p
            if target_dist < 0.03:
                continue

            # Recovery Lot Sizing:
            if deficit > 0:
                lot = min(0.12, max(0.05, round((deficit + 30.0) / (target_dist * mult), 2)))
            else:
                lot = 0.05

            sl_p = entry_p - (0.85 * target_dist)
            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 25, n)):
                if not be_active and h[k] >= entry_p + (0.40 * target_dist):
                    sl_p = entry_p + 0.005
                    be_active = True

                if l[k] <= sl_p:
                    pnl = (sl_p - entry_p) * mult * lot
                    last_exit_idx = k
                    break
                elif h[k] >= target_p:
                    pnl = (target_p - entry_p) * mult * lot
                    last_exit_idx = k
                    break
            else:
                pnl = (c[min(i + 25, n) - 1] - entry_p) * mult * lot
                last_exit_idx = min(i + 25, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if day_pnl > 0:
                locked_green = True # THE DAY IS WON!
                deficit = 0.0
            else:
                deficit = abs(day_pnl)

        elif short_c:
            entry_p = o[i]
            target_p = mid[i-1]
            target_dist = entry_p - target_p
            if target_dist < 0.03:
                continue

            if deficit > 0:
                lot = min(0.12, max(0.05, round((deficit + 30.0) / (target_dist * mult), 2)))
            else:
                lot = 0.05

            sl_p = entry_p + (0.85 * target_dist)
            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 25, n)):
                if not be_active and l[k] <= entry_p - (0.40 * target_dist):
                    sl_p = entry_p - 0.005
                    be_active = True

                if h[k] >= sl_p:
                    pnl = (entry_p - sl_p) * mult * lot
                    last_exit_idx = k
                    break
                elif l[k] <= target_p:
                    pnl = (entry_p - target_p) * mult * lot
                    last_exit_idx = k
                    break
            else:
                pnl = (entry_p - c[min(i + 25, n) - 1]) * mult * lot
                last_exit_idx = min(i + 25, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if day_pnl > 0:
                locked_green = True
                deficit = 0.0
            else:
                deficit = abs(day_pnl)

    if current_day is not None and current_day not in daily_results:
        daily_results[current_day] = {
            'pnl': day_pnl,
            'trades': len(day_trades),
            'wins': sum(1 for t in day_trades if t['pnl'] > 0),
            'losses': sum(1 for t in day_trades if t['pnl'] <= 0),
        }

    res_df = pd.DataFrame.from_dict(daily_results, orient='index').reset_index().rename(columns={'index': 'date'})
    active_days = res_df[res_df['trades'] > 0]
    green_days = active_days[active_days['pnl'] > 0]
    red_days = active_days[active_days['pnl'] < 0]

    print("=" * 75)
    print("  DEFINITIVE RESULT: MACRO FILTER + SESSION RECOVERY GOVERNOR")
    print("=" * 75)
    print(f"Total Active Trading Days: {len(active_days)}")
    print(f"GREEN DAYS               : {len(green_days)} of {len(active_days)} ({len(green_days)/len(active_days)*100:.1f}%)")
    print(f"RED DAYS                 : {len(red_days)}")
    print(f"Total Net PnL            : +${active_days['pnl'].sum():,.2f}")
    print(f"Total Trades Taken       : {active_days['trades'].sum()} ({active_days['wins'].sum()} Wins / {active_days['losses'].sum()} Losses)")
    print(f"Profit Factor            : {active_days[active_days['pnl']>0]['pnl'].sum() / abs(active_days[active_days['pnl']<0]['pnl'].sum() if len(red_days)>0 else 1.0):.2f}")

    print("\n" + "=" * 75)
    print("  EXACT DAY-BY-DAY AUDIT RECORD:")
    print("=" * 75)
    for _, r in active_days.iterrows():
        status = "GREEN (SESSION WON & LOCKED)" if r['pnl'] > 0 else "RED"
        print(f"  {r['date']} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | PnL: ${r['pnl']:+8.2f} [{status}]")

run_silver_daily_master_session()
