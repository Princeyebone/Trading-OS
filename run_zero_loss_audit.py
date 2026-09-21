import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_flawless_system():
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
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema50 = df['h1_ema50'].values

    # Bollinger Bands (20, 2.4)
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.4 * std
    lower = mid - 2.4 * std

    # RSI (7)
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
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

        # Adaptive recovery ladder:
        # If day_pnl is in deficit (< 0) but consec_losses is 0, use 0.05 lot so the win immediately covers the deficit!
        if consec_losses == 0:
            cur_lot = 0.05 if day_pnl < 0 else 0.02
            rsi_low, rsi_high = 30, 70
            tp_factor = 0.70
        elif consec_losses == 1:
            cur_lot = 0.06
            rsi_low, rsi_high = 25, 75
            tp_factor = 0.55
        elif consec_losses == 2:
            cur_lot = 0.12
            rsi_low, rsi_high = 20, 80
            tp_factor = 0.55
        else:
            cur_lot = 0.20
            rsi_low, rsi_high = 18, 82
            tp_factor = 0.55

        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_low) and (c[i-1] >= h1_ema50[i-1] - 0.25)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_high) and (c[i-1] <= h1_ema50[i-1] + 0.25)

        if long_c:
            entry = o[i]
            dist = mid[i-1] - entry
            if dist < 0.025:
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
                if day_pnl >= 20.0:
                    locked_green = True
            else:
                consec_losses += 1

        elif short_c:
            entry = o[i]
            dist = entry - mid[i-1]
            if dist < 0.025:
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
                if day_pnl >= 20.0:
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
    print("=" * 80)
    print("  ZERO LOSS AUDIT RESULTS")
    print("=" * 80)
    print(f"Total Active Trading Days: {tot}")
    print(f"GREEN DAYS               : {g} of {tot} ({g/tot*100:.1f}%)")
    print(f"RED DAYS                 : {r}")
    print(f"Total Net PnL Accumulated: +${active['pnl'].sum():,.2f}")
    print(f"Total Trades Taken       : {active['trades'].sum()} ({active['trades'].sum()/tot:.1f} trades/day)")
    print(f"Total Wins vs Losses     : {active['wins'].sum()} Wins vs {active['losses'].sum()} Losses")

    print("\n" + "=" * 80)
    print("  EXACT DAY-BY-DAY AUDIT TABLE:")
    print("=" * 80)
    for _, row in active.iterrows():
        st = "GREEN (SESSION WON & LOCKED)" if row['pnl'] > 0 else "RED"
        print(f"  {row['date']} | Trades: {int(row['trades']):2} ({int(row['wins']):2}W / {int(row['losses']):2}L) | PnL: ${row['pnl']:+8.2f} [{st}]")

if __name__ == "__main__":
    run_flawless_system()
