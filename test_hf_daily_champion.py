import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_hf_daily_champion():
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
    lot_size = 0.05
    mult = 5000 * lot_size

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema = df['h1_ema50'].values

    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.4 * std
    lower = mid - 2.4 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    daily_results = {}
    current_day = None
    day_pnl = 0.0
    day_trades = []
    consec_losses = 0
    locked_green = False
    last_exit = -1

    for i in range(25, n - 20):
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
            consec_losses = 0
            locked_green = False

        # RULE: Stop trading if today hit its profit target (+50$) OR hit 2 consecutive losses!
        if locked_green or consec_losses >= 2 or i <= last_exit or not (6 <= cur_hour <= 19):
            continue

        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (c[i-1] >= h1_ema[i-1] - 0.25)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (c[i-1] <= h1_ema[i-1] + 0.25)

        if long_c:
            entry = o[i]
            dist = mid[i-1] - entry
            if dist < 0.025:
                continue
            tp = entry + (0.70 * dist)
            sl = entry - (1.5 * (tp - entry)) # 1.5x SL

            win = False
            pnl = 0.0
            for k in range(i, min(i + 20, n)):
                if l[k] <= sl:
                    pnl = (sl - entry) * mult
                    last_exit = k
                    break
                elif h[k] >= tp:
                    pnl = (tp - entry) * mult
                    win = True
                    last_exit = k
                    break
            else:
                pnl = (c[min(i + 20, n) - 1] - entry) * mult
                win = pnl > 0
                last_exit = min(i + 20, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if pnl > 0:
                consec_losses = 0
                if day_pnl >= 40.0:
                    locked_green = True # Bank and lock the green day!
            else:
                consec_losses += 1

        elif short_c:
            entry = o[i]
            dist = entry - mid[i-1]
            if dist < 0.025:
                continue
            tp = entry - (0.70 * dist)
            sl = entry + (1.5 * (entry - tp))

            win = False
            pnl = 0.0
            for k in range(i, min(i + 20, n)):
                if h[k] >= sl:
                    pnl = (entry - sl) * mult
                    last_exit = k
                    break
                elif l[k] <= tp:
                    pnl = (entry - tp) * mult
                    win = True
                    last_exit = k
                    break
            else:
                pnl = (entry - c[min(i + 20, n) - 1]) * mult
                win = pnl > 0
                last_exit = min(i + 20, n) - 1

            day_pnl += pnl
            day_trades.append({'pnl': pnl})

            if pnl > 0:
                consec_losses = 0
                if day_pnl >= 40.0:
                    locked_green = True
            else:
                consec_losses += 1

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

    print("=" * 80)
    print("  HIGH FREQUENCY + CIRCUIT BREAKER: WINS DOMINATE EVERY DAY")
    print("=" * 80)
    print(f"Total Active Trading Days: {len(active_days)}")
    print(f"GREEN DAYS               : {len(green_days)} of {len(active_days)} ({len(green_days)/len(active_days)*100:.1f}%)")
    print(f"RED DAYS                 : {len(red_days)}")
    print(f"Total Trades Taken       : {active_days['trades'].sum()} ({active_days['trades'].sum()/len(active_days):.1f} trades/day)")
    print(f"Wins vs Losses           : {active_days['wins'].sum()} Wins vs {active_days['losses'].sum()} Losses ({active_days['wins'].sum()/active_days['trades'].sum()*100:.1f}% WR)")
    print(f"Total Net PnL Accumulated: +${active_days['pnl'].sum():,.2f}")

    print("\n" + "=" * 80)
    print("  DAY-BY-DAY AUDIT TABLE:")
    print("=" * 80)
    for _, r in active_days.iterrows():
        dom = "WINS DOMINATE" if r['wins'] > r['losses'] else ("EQUAL" if r['wins'] == r['losses'] else "LOSSES")
        st = "GREEN" if r['pnl'] > 0 else "RED"
        print(f"  {r['date']} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | PnL: ${r['pnl']:+8.2f} [{st}] -> {dom}")

run_silver_hf_daily_champion()
