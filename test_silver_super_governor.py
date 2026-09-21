import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_super_governor():
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

    lot_size = 0.05
    mult = 5000

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

    # Higher Timeframe Trend Filter (EMA 100 on M5 = ~8.5 hours)
    ema100 = pd.Series(c).ewm(span=100, adjust=False).mean().values

    # ADX(14)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.insert(tr, 0, h[0] - l[0])
    up_move = np.insert(h[1:] - h[:-1], 0, 0)
    down_move = np.insert(l[:-1] - l[1:], 0, 0)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    alpha = 1.0 / 14.0
    tr_smooth = pd.Series(tr).ewm(alpha=alpha, adjust=False).mean().values
    plus_di = 100 * (pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean().values / (tr_smooth + 1e-9))
    minus_di = 100 * (pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean().values / (tr_smooth + 1e-9))
    dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9))
    adx = pd.Series(dx).ewm(alpha=alpha, adjust=False).mean().values

    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    # Let's test adding:
    # 1. Trend Alignment (never fade against the EMA 100 on trend runaway days)
    # 2. ADX Filter (do not take trades when ADX > 32 - strong trending expansion)
    # 3. Daily Profit Lock: Stop day after banking +$40.00
    
    daily_results = {}
    current_day = None
    day_pnl = 0.0
    day_locked = False
    day_trades = []
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

        if day_locked:
            continue

        if i <= last_exit_idx:
            continue

        if not (7 <= cur_hour <= 18):
            continue

        # FILTER 1: Don't fight extreme runaway trend bars (ADX > 30)
        if adx[i-1] > 30:
            continue

        # FILTER 2: Trend Alignment (Long only if price > EMA 100 or within 0.15 pts; Short only if price < EMA 100 or within 0.15 pts)
        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (lower_wick[i-1] >= body[i-1]) and (c[i-1] >= ema100[i-1] - 0.20)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (upper_wick[i-1] >= body[i-1]) and (c[i-1] <= ema100[i-1] + 0.20)

        if long_c:
            entry_p = o[i]
            mid_dist = mid[i-1] - entry_p
            if mid_dist < 0.03:
                continue

            tp1 = mid[i-1]
            sl_p = entry_p - (0.80 * mid_dist) # tight SL

            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 35, n)):
                if not be_active and h[k] >= entry_p + (0.40 * mid_dist):
                    sl_p = entry_p + 0.005
                    be_active = True

                if l[k] <= sl_p:
                    pnl = (sl_p - entry_p) * mult * lot_size
                    last_exit_idx = k
                    break
                elif h[k] >= tp1:
                    pnl = (tp1 - entry_p) * mult * lot_size
                    last_exit_idx = k
                    break
            else:
                pnl = (c[min(i + 35, n) - 1] - entry_p) * mult * lot_size
                last_exit_idx = min(i + 35, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if day_pnl >= 35.0: # Lock in positive day!
                day_locked = True

        elif short_c:
            entry_p = o[i]
            mid_dist = entry_p - mid[i-1]
            if mid_dist < 0.03:
                continue

            tp1 = mid[i-1]
            sl_p = entry_p + (0.80 * mid_dist)

            pnl = 0.0
            be_active = False

            for k in range(i, min(i + 35, n)):
                if not be_active and l[k] <= entry_p - (0.40 * mid_dist):
                    sl_p = entry_p - 0.005
                    be_active = True

                if h[k] >= sl_p:
                    pnl = (entry_p - sl_p) * mult * lot_size
                    last_exit_idx = k
                    break
                elif l[k] <= tp1:
                    pnl = (entry_p - tp1) * mult * lot_size
                    last_exit_idx = k
                    break
            else:
                pnl = (entry_p - c[min(i + 35, n) - 1]) * mult * lot_size
                last_exit_idx = min(i + 35, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if day_pnl >= 35.0:
                day_locked = True

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
    print("  TREND-PROTECTED DAILY GOVERNOR SYSTEM (SILVER XAGUSD)")
    print("=" * 75)
    print(f"Total Active Trading Days: {len(active_days)}")
    print(f"Green Days               : {len(green_days)} of {len(active_days)} ({len(green_days)/len(active_days)*100:.1f}%)")
    print(f"Red Days                 : {len(red_days)}")
    print(f"Total Net PnL            : +${active_days['pnl'].sum():,.2f}")
    print(f"Total Trades Taken       : {active_days['trades'].sum()} ({active_days['wins'].sum()} Wins / {active_days['losses'].sum()} Losses)")
    print(f"Overall Trade Win Rate   : {active_days['wins'].sum()/active_days['trades'].sum()*100:.1f}%")

    print("\n" + "=" * 75)
    print("  EXACT DAY-BY-DAY AUDIT RECORD:")
    print("=" * 75)
    for _, r in active_days.iterrows():
        status = "GREEN (TARGET BANKED)" if r['pnl'] >= 30 else ("GREEN" if r['pnl'] > 0 else "RED")
        print(f"  {r['date']} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | PnL: ${r['pnl']:+8.2f} [{status}]")

run_silver_super_governor()
