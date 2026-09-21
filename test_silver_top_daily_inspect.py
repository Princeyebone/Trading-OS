import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_top_daily_inspect():
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
    mult = 5000 * lot_size # $250 per $1.00 move

    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema50']], on='time', direction='backward')
    h1_ema = df['h1_ema50'].values

    # Winning Configuration:
    # BB dev 2.4, RSI(7) 30/70, Target 0.70x of mid-band distance, SL 1.8x target distance
    # With H1 Trend filter:
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.4 * std
    lower = mid - 2.4 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    trades = []
    last_exit = -1

    for i in range(25, n - 20):
        if i <= last_exit:
            continue

        hr = df['hour'].iloc[i]
        if not (6 <= hr <= 19):
            continue

        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30) and (c[i-1] >= h1_ema[i-1] - 0.25)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70) and (c[i-1] <= h1_ema[i-1] + 0.25)

        if long_c:
            entry = o[i]
            dist = mid[i-1] - entry
            if dist < 0.025:
                continue
            tp = entry + (0.70 * dist)
            sl = entry - (1.8 * (tp - entry))

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

            trades.append({'date': str(df['date'].iloc[i]), 'win': win, 'pnl': pnl})

        elif short_c:
            entry = o[i]
            dist = entry - mid[i-1]
            if dist < 0.025:
                continue
            tp = entry - (0.70 * dist)
            sl = entry + (1.8 * (entry - tp))

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

            trades.append({'date': str(df['date'].iloc[i]), 'win': win, 'pnl': pnl})

    tdf = pd.DataFrame(trades)
    daily = tdf.groupby('date').agg(
        trades=('win', 'count'),
        wins=('win', lambda x: (x == True).sum()),
        losses=('win', lambda x: (x == False).sum()),
        pnl=('pnl', 'sum')
    ).reset_index()

    daily['win_rate'] = (daily['wins'] / daily['trades']) * 100
    w_gt_l = len(daily[daily['wins'] > daily['losses']])
    green_days = len(daily[daily['pnl'] > 0])

    print("=" * 80)
    print("  HIGH-FREQUENCY SILVER HYPER SCALPER: EXACT DAY-BY-DAY RESULTS")
    print("=" * 80)
    print(f"Total Calendar Days Analyzed   : {len(daily)} days")
    print(f"Total Trades Taken             : {len(tdf)} trades ({len(tdf)/len(daily):.1f} trades / day)")
    print(f"Days Where Wins Outnumber Losses: {w_gt_l} of {len(daily)} days ({(w_gt_l/len(daily)*100):.1f}%)")
    print(f"Green Winning Days             : {green_days} of {len(daily)} days ({(green_days/len(daily)*100):.1f}%)")
    print(f"Total Overall Win Rate         : {tdf['win'].mean()*100:.1f}% ({tdf['win'].sum()} Wins / {(~tdf['win']).sum()} Losses)")
    print(f"Total Net Profit (0.05 Lot)    : +${tdf['pnl'].sum():,.2f}")

    print("\n" + "=" * 80)
    print("  EXACT DAY-BY-DAY AUDIT TABLE:")
    print("=" * 80)
    for _, r in daily.iterrows():
        dom = "WINS DOMINATE" if r['wins'] > r['losses'] else ("EQUAL" if r['wins'] == r['losses'] else "LOSSES")
        st = "GREEN" if r['pnl'] > 0 else "RED"
        print(f"  {r['date']} | Trades: {int(r['trades']):2} ({int(r['wins']):2}W / {int(r['losses']):2}L) | Win Rate: {r['win_rate']:5.1f}% | PnL: ${r['pnl']:+8.2f} [{st}] -> {dom}")

if __name__ == "__main__":
    run_silver_top_daily_inspect()
