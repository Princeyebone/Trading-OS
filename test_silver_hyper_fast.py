import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_hyper_vectorized():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    # Fetch last 4000 M5 candles (approx 3 weeks of high-speed scalping data)
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 4000)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print("No rates returned")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    n = len(df)

    # ATR(14)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.insert(tr, 0, h[0] - l[0])
    atr = pd.Series(tr).rolling(14).mean().values

    # RSI(14)
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    lot_size = 0.05
    mult = 5000 * lot_size # $250 per $1.00 move

    print(f"Candles loaded: {n} M5 bars ({df['date'].min()} to {df['date'].max()})")

    results = []

    # Test parameter combos
    for dev in [2.0, 2.2, 2.4]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + dev * std
        lower = mid - dev * std

        for rsi_thresh in [(40, 60), (35, 65), (30, 70)]:
            r_low, r_high = rsi_thresh
            for sl_ratio in [1.2, 1.5, 2.0]:
                for max_hold in [12, 24, 36]: # hold max 12 bars (1 hr) or 24 bars (2 hr)
                    trades = []
                    last_exit_idx = -1

                    for i in range(25, n - max_hold):
                        if i <= last_exit_idx:
                            continue

                        # Previous candle check (index i-1)
                        # Mean reversion Long: close below lower BB and oversold RSI
                        long_entry = (c[i-1] < lower[i-1]) and (rsi[i-1] < r_low)
                        # Mean reversion Short: close above upper BB and overbought RSI
                        short_entry = (c[i-1] > upper[i-1]) and (rsi[i-1] > r_high)

                        if long_entry:
                            entry_p = o[i]
                            target_p = mid[i-1]
                            target_dist = target_p - entry_p
                            if target_dist < 0.02: # skip negligible targets
                                continue
                            sl_p = entry_p - (sl_ratio * target_dist) # dynamic SL based on target distance

                            # evaluate outcome
                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + max_hold, n)):
                                if l[k] <= sl_p:
                                    pnl = (sl_p - entry_p) * mult
                                    last_exit_idx = k
                                    break
                                elif h[k] >= target_p:
                                    pnl = (target_p - entry_p) * mult
                                    win = True
                                    last_exit_idx = k
                                    break
                            else: # timed out
                                pnl = (c[min(i + max_hold, n) - 1] - entry_p) * mult
                                win = pnl > 0
                                last_exit_idx = min(i + max_hold, n) - 1

                            trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                        elif short_entry:
                            entry_p = o[i]
                            target_p = mid[i-1]
                            target_dist = entry_p - target_p
                            if target_dist < 0.02:
                                continue
                            sl_p = entry_p + (sl_ratio * target_dist)

                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + max_hold, n)):
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
                                pnl = (entry_p - c[min(i + max_hold, n) - 1]) * mult
                                win = pnl > 0
                                last_exit_idx = min(i + max_hold, n) - 1

                            trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                    if len(trades) >= 15:
                        tdf = pd.DataFrame(trades)
                        w = (tdf['win'] == True).sum()
                        l_count = (tdf['win'] == False).sum()
                        wr = w / len(tdf) * 100
                        pnl = tdf['pnl'].sum()
                        gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
                        gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
                        pf = gp / (gl if gl > 0 else 1.0)

                        # Check day by day stats
                        daily = tdf.groupby('date').agg(
                            tw=('win', lambda x: (x == True).sum()),
                            tl=('win', lambda x: (x == False).sum()),
                            dpnl=('pnl', 'sum')
                        )
                        green_days = (daily['dpnl'] > 0).sum()
                        red_days = (daily['dpnl'] < 0).sum()
                        daily_wr = green_days / len(daily) * 100

                        results.append({
                            'dev': dev,
                            'rsi': f"{r_low}/{r_high}",
                            'sl_ratio': sl_ratio,
                            'max_hold': max_hold,
                            'trades': len(tdf),
                            'win_rate': wr,
                            'wins': w,
                            'losses': l_count,
                            'pnl': pnl,
                            'pf': pf,
                            'green_days': green_days,
                            'red_days': red_days,
                            'daily_wr': daily_wr
                        })

    rdf = pd.DataFrame(results)
    rdf = rdf.sort_values(by=['win_rate', 'pf'], ascending=[False, False])
    print(f"\nTested {len(results)} distinct parameter configurations.")
    print("\nTOP 10 CONFIGURATIONS WITH WINS HEAVILY OUTNUMBERING LOSSES:")
    print(rdf.head(10).to_string(index=False))

    best = rdf.iloc[0]
    print(f"\nBEST OVERALL FORMULA FOR SILVER HYPER SCALPER:")
    print(f"BB Deviation: {best['dev']}, RSI: {best['rsi']}, SL Ratio: {best['sl_ratio']}, Max Hold: {best['max_hold']} bars")
    print(f"Trades: {best['trades']} | Win Rate: {best['win_rate']:.1f}% ({best['wins']} Wins vs {best['losses']} Losses)")
    print(f"Daily Consistency: {best['green_days']} Green Days vs {best['red_days']} Red Days ({best['daily_wr']:.1f}% Green Days)")
    print(f"Profit Factor: {best['pf']:.2f} | Net Profit: +${best['pnl']:,.2f}")

run_silver_hyper_vectorized()
