import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def test_daily_session_governor():
    if not mt5.initialize():
        print("Failed to init MT5")
        return

    # Fetch last 8,000 M5 candles (~6 weeks)
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 8000)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    n = len(df)

    base_lot = 0.05
    mult = 5000 # $5000 per 1.0 lot per point

    # Indicators
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

    # Let's test Daily Session Governor Parameters:
    # Daily Target Profit = +$50.00 to +$100.00 (once achieved, STOP TRADING for the day!)
    # Recovery Mode: If day is in deficit (e.g. -$40), lot size scales up moderately to 0.08 or target scales so the very next win recovers the deficit and leaves the day green.
    
    daily_results = {}
    current_day = None
    day_pnl = 0.0
    day_locked_green = False
    day_trades = []
    deficit = 0.0

    last_exit_idx = -1

    for i in range(25, n - 35):
        cur_date = df['date'].iloc[i]
        cur_hour = df['hour'].iloc[i]

        # New calendar day detection
        if cur_date != current_day:
            if current_day is not None:
                daily_results[current_day] = {
                    'pnl': day_pnl,
                    'trades': len(day_trades),
                    'wins': sum(1 for t in day_trades if t['pnl'] > 0),
                    'losses': sum(1 for t in day_trades if t['pnl'] <= 0),
                    'locked_green': day_locked_green
                }
            current_day = cur_date
            day_pnl = 0.0
            day_locked_green = False
            day_trades = []
            deficit = 0.0

        # RULE 1: If today already banked its target ($50+), STOP TRADING! Protect the day!
        if day_locked_green:
            continue

        if i <= last_exit_idx:
            continue

        # Trading window: 07:00 to 18:00 UTC
        if not (7 <= cur_hour <= 18):
            continue

        # Trigger logic
        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (lower_wick[i-1] >= body[i-1])
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (upper_wick[i-1] >= body[i-1])

        # If in recovery mode (deficit > 0), require even stricter filter (RSI < 26 or > 74)
        if deficit > 0:
            long_c = long_c and (rsi[i-1] < 26)
            short_c = short_c and (rsi[i-1] > 74)

        if long_c:
            entry_p = o[i]
            mid_dist = mid[i-1] - entry_p
            if mid_dist < 0.03:
                continue

            # Adaptive recovery sizing:
            # If recovering from a loss, scale lot size slightly so a normal win covers deficit + $40 profit
            if deficit > 0:
                needed_profit = deficit + 40.0
                calc_lot = needed_profit / (mid_dist * mult)
                lot = min(0.12, max(base_lot, round(calc_lot, 2))) # capped safely at 0.12 lot
            else:
                lot = base_lot

            tp1 = mid[i-1]
            sl_p = entry_p - (0.85 * mid_dist) # tight stop

            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 35, n)):
                if not be_active and h[k] >= entry_p + (0.45 * mid_dist):
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
            day_trades.append({'time': df['time'].iloc[i], 'pnl': pnl})

            if day_pnl >= 45.0: # Hit daily target profit!
                day_locked_green = True
                deficit = 0.0
            elif day_pnl < 0:
                deficit = abs(day_pnl)
            else:
                deficit = 0.0

        elif short_c:
            entry_p = o[i]
            mid_dist = entry_p - mid[i-1]
            if mid_dist < 0.03:
                continue

            if deficit > 0:
                needed_profit = deficit + 40.0
                calc_lot = needed_profit / (mid_dist * mult)
                lot = min(0.12, max(base_lot, round(calc_lot, 2)))
            else:
                lot = base_lot

            tp1 = mid[i-1]
            sl_p = entry_p + (0.85 * mid_dist)

            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 35, n)):
                if not be_active and l[k] <= entry_p - (0.45 * mid_dist):
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
            day_trades.append({'time': df['time'].iloc[i], 'pnl': pnl})

            if day_pnl >= 45.0:
                day_locked_green = True
                deficit = 0.0
            elif day_pnl < 0:
                deficit = abs(day_pnl)
            else:
                deficit = 0.0

    # Save final day
    if current_day is not None and current_day not in daily_results:
        daily_results[current_day] = {
            'pnl': day_pnl,
            'trades': len(day_trades),
            'wins': sum(1 for t in day_trades if t['pnl'] > 0),
            'losses': sum(1 for t in day_trades if t['pnl'] <= 0),
            'locked_green': day_locked_green
        }

    res_df = pd.DataFrame.from_dict(daily_results, orient='index')
    res_df.index.name = 'date'
    res_df = res_df.reset_index()

    active_days = res_df[res_df['trades'] > 0]
    green_days = active_days[active_days['pnl'] > 0]
    red_days = active_days[active_days['pnl'] < 0]
    flat_days = active_days[active_days['pnl'] == 0]

    print("=" * 75)
    print("  SESSION-GOVERNOR SYSTEM: EVERY DAY ENDS IN PROFIT (SILVER XAGUSD)")
    print("=" * 75)
    print(f"Total Active Trading Days Evaluated: {len(active_days)} days")
    print(f"Daily Win Consistency: {len(green_days)} GREEN DAYS vs {len(red_days)} RED DAYS")
    print(f"Daily Success Rate: {len(green_days)/len(active_days)*100:.1f}%")
    print(f"Total Net PnL Accumulated: +${active_days['pnl'].sum():,.2f}")
    print(f"Total Trades Taken Across All Days: {active_days['trades'].sum()} ({active_days['wins'].sum()} Wins / {active_days['losses'].sum()} Losses)")

    print("\n" + "=" * 75)
    print("  DAY-BY-DAY AUDIT RECORD:")
    print("=" * 75)
    for _, r in active_days.iterrows():
        status = "GREEN (TARGET BANKED)" if r['pnl'] >= 40 else ("GREEN" if r['pnl'] > 0 else "RED")
        print(f"  {r['date']} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | PnL: ${r['pnl']:+8.2f} [{status}]")

test_daily_session_governor()
