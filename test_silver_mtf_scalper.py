import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_multi_timeframe_silver_search():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    # Fetch 4000 M5 bars
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 4000)
    mt5.shutdown()

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    n = len(df)

    # 1. M5 Indicators
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std

    # RSI
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    # 2. Higher Timeframe Trend Filter (H1 Trend)
    # 200 M5 periods is ~16 hours, 300 M5 periods is ~25 hours (daily trend line)
    ema_trend = pd.Series(c).ewm(span=200, adjust=False).mean().values
    ema_fast = pd.Series(c).ewm(span=50, adjust=False).mean().values

    # 3. Candle Rejection Pattern:
    # Bullish Pinbar / Hammer on M5: lower wick >= 2x body
    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    lot_size = 0.05
    mult = 5000 * lot_size

    # Test filtering rules
    filters = [
        ("Base BB(2.0) + RSI(30/70) [No Trend]", False, False),
        ("Trend-Aligned Only (Buy > EMA200, Sell < EMA200)", True, False),
        ("Wick Rejection Confirmation (Hammer/Shooting Star)", False, True),
        ("Trend-Aligned + Wick Rejection (Combined)", True, True)
    ]

    for label, use_trend, use_wick in filters:
        trades = []
        last_exit_idx = -1

        for i in range(25, n - 24):
            if i <= last_exit_idx:
                continue

            # Long Setup:
            # Over-extension below lower BB + RSI oversold
            long_cond = (c[i-1] < lower[i-1]) and (rsi[i-1] < 35)
            if use_trend:
                long_cond = long_cond and (c[i-1] > ema_trend[i-1])
            if use_wick:
                long_cond = long_cond and (lower_wick[i-1] > body[i-1])

            # Short Setup:
            short_cond = (c[i-1] > upper[i-1]) and (rsi[i-1] > 65)
            if use_trend:
                short_cond = short_cond and (c[i-1] < ema_trend[i-1])
            if use_wick:
                short_cond = short_cond and (upper_wick[i-1] > body[i-1])

            if long_cond:
                entry_p = o[i]
                target_p = mid[i-1]
                target_dist = target_p - entry_p
                if target_dist < 0.025:
                    continue
                sl_p = entry_p - (1.2 * target_dist)

                win = False
                pnl = 0.0
                for k in range(i, min(i + 24, n)):
                    if l[k] <= sl_p:
                        pnl = (sl_p - entry_p) * mult
                        last_exit_idx = k
                        break
                    elif h[k] >= target_p:
                        pnl = (target_p - entry_p) * mult
                        win = True
                        last_exit_idx = k
                        break
                else:
                    pnl = (c[min(i + 24, n) - 1] - entry_p) * mult
                    win = pnl > 0
                    last_exit_idx = min(i + 24, n) - 1

                trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

            elif short_cond:
                entry_p = o[i]
                target_p = mid[i-1]
                target_dist = entry_p - target_p
                if target_dist < 0.025:
                    continue
                sl_p = entry_p + (1.2 * target_dist)

                win = False
                pnl = 0.0
                for k in range(i, min(i + 24, n)):
                    if h[k] >= sl_p:
                        pnl = (entry_p - sl_p) * mult
                        last_exit_idx = k
                        break
                    elif l[k] <= target_p:
                        pnl = (entry_p - target_p) * mult
                        win = True
                        last_exit_idx = k
                        break
                else:
                    pnl = (entry_p - c[min(i + 24, n) - 1]) * mult
                    win = pnl > 0
                    last_exit_idx = min(i + 24, n) - 1

                trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

        if len(trades) > 0:
            tdf = pd.DataFrame(trades)
            w = (tdf['win'] == True).sum()
            l_count = (tdf['win'] == False).sum()
            wr = w / len(tdf) * 100
            pnl = tdf['pnl'].sum()
            gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
            gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
            pf = gp / (gl if gl > 0 else 1.0)

            daily = tdf.groupby('date').agg(
                trades=('win', 'count'),
                w=('win', lambda x: (x == True).sum()),
                l=('win', lambda x: (x == False).sum()),
                pnl=('pnl', 'sum')
            )
            green_days = (daily['pnl'] > 0).sum()
            red_days = (daily['pnl'] < 0).sum()

            print(f"\n========================================================")
            print(f"  {label}")
            print(f"========================================================")
            print(f"Total Trades Taken        : {len(tdf)}")
            print(f"Trade Win Rate            : {wr:.1f}% ({w} Wins vs {l_count} Losses)")
            print(f"Profit Factor             : {pf:.2f}")
            print(f"Total Net PnL (0.05 lot)  : +${pnl:,.2f}")
            print(f"Active Trading Days       : {len(daily)} days")
            print(f"Daily Consistency         : {green_days} Green Days vs {red_days} Red Days ({(green_days/len(daily)*100):.1f}% Green Days)")
            print(f"Average Trades per Day    : {len(tdf)/len(daily):.1f} trades/day")

            print("\nDaily Breakdown Sample (Last 8 Active Days):")
            for d, r in daily.tail(8).iterrows():
                status = "GREEN" if r['pnl'] > 0 else ("RED" if r['pnl'] < 0 else "FLAT")
                print(f"  {d} | Trades: {int(r['trades']):2} ({int(r['w'])}W/{int(r['l'])}L) | WinRate: {r['w']/r['trades']*100:5.1f}% | PnL: ${r['pnl']:+8.2f} [{status}]")

run_multi_timeframe_silver_search()
