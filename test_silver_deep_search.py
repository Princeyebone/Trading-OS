import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_deep_search():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    # Fetch last 6,000 M5 candles (~4 weeks of high-resolution data)
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 6000)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print("No rates returned")
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

    lot_size = 0.05
    mult = 5000 * lot_size # $250 per $1.00 move

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

    # EMA 50 & EMA 200 for higher timeframe trend
    ema50 = pd.Series(c).ewm(span=50, adjust=False).mean().values
    ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().values

    # Bollinger Bands 20, dev=2.2
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.2 * std
    lower = mid - 2.2 * std

    # CANDLE WICK RATIO:
    # A genuine rejection candle has a long wick poking outside the band
    body = np.abs(c - o)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    results = []

    # Let's test combinations of:
    # 1. Trailing Break-Even Trigger: when trade reaches +50% of target distance, move SL to entry + $0.01 (Scratch out bad trades!)
    # 2. Asymmetric TP / SL: Target = 1.0x to 1.2x of (mid - entry), SL = 1.0x (Equal or better RR so 1 loss never wipes out 2 wins)
    # 3. Daily Loss Circuit Breaker: Max 2 consecutive losses in a single day, then stop trading for that day!
    # 4. Trend Filter: Only trade in the direction of the EMA 200 (or EMA 50)
    # 5. Wick Confirmation: Require wick > body to confirm actual rejection before entry

    for be_trigger in [0.0, 0.4, 0.5]: # 0.0 = no BE, 0.5 = move to BE when halfway to TP
        for sl_mult in [0.8, 1.0, 1.2]: # tighter SL so losses are SMALL
            for use_trend in [False, True]:
                for use_circuit_breaker in [False, True]: # stop day after 2 losses
                    for use_wick in [False, True]:
                        trades = []
                        last_exit_idx = -1
                        daily_losses = {} # date -> count of losses

                        for i in range(25, n - 25):
                            if i <= last_exit_idx:
                                continue

                            cur_date = df['date'].iloc[i]
                            cur_hour = df['hour'].iloc[i]

                            # Active European & US volume
                            if not (7 <= cur_hour <= 18):
                                continue

                            # Circuit Breaker check
                            if use_circuit_breaker and daily_losses.get(cur_date, 0) >= 2:
                                continue

                            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30)
                            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70)

                            if use_trend:
                                long_c = long_c and (c[i-1] > ema200[i-1])
                                short_c = short_c and (c[i-1] < ema200[i-1])

                            if use_wick:
                                long_c = long_c and (lower_wick[i-1] >= body[i-1])
                                short_c = short_c and (upper_wick[i-1] >= body[i-1])

                            if long_c:
                                entry_p = o[i]
                                target_p = mid[i-1]
                                target_dist = target_p - entry_p
                                if target_dist < 0.03:
                                    continue
                                sl_p = entry_p - (sl_mult * target_dist)

                                win = False
                                pnl = 0.0
                                be_active = False

                                for k in range(i, min(i + 25, n)):
                                    # check break-even trigger
                                    if be_trigger > 0.0 and not be_active:
                                        if h[k] >= entry_p + (be_trigger * target_dist):
                                            sl_p = entry_p + 0.005 # locked to BE / small scratch
                                            be_active = True

                                    if l[k] <= sl_p:
                                        pnl = (sl_p - entry_p) * mult
                                        win = pnl > 0
                                        last_exit_idx = k
                                        break
                                    elif h[k] >= target_p:
                                        pnl = (target_p - entry_p) * mult
                                        win = True
                                        last_exit_idx = k
                                        break
                                else:
                                    pnl = (c[min(i + 25, n) - 1] - entry_p) * mult
                                    win = pnl > 0
                                    last_exit_idx = min(i + 25, n) - 1

                                if not win:
                                    daily_losses[cur_date] = daily_losses.get(cur_date, 0) + 1
                                trades.append({'date': cur_date, 'win': win, 'pnl': pnl})

                            elif short_c:
                                entry_p = o[i]
                                target_p = mid[i-1]
                                target_dist = entry_p - target_p
                                if target_dist < 0.03:
                                    continue
                                sl_p = entry_p + (sl_mult * target_dist)

                                win = False
                                pnl = 0.0
                                be_active = False

                                for k in range(i, min(i + 25, n)):
                                    if be_trigger > 0.0 and not be_active:
                                        if l[k] <= entry_p - (be_trigger * target_dist):
                                            sl_p = entry_p - 0.005
                                            be_active = True

                                    if h[k] >= sl_p:
                                        pnl = (entry_p - sl_p) * mult
                                        win = pnl > 0
                                        last_exit_idx = k
                                        break
                                    elif l[k] <= target_p:
                                        pnl = (entry_p - target_p) * mult
                                        win = True
                                        last_exit_idx = k
                                        break
                                else:
                                    pnl = (entry_p - c[min(i + 25, n) - 1]) * mult
                                    win = pnl > 0
                                    last_exit_idx = min(i + 25, n) - 1

                                if not win:
                                    daily_losses[cur_date] = daily_losses.get(cur_date, 0) + 1
                                trades.append({'date': cur_date, 'win': win, 'pnl': pnl})

                        if len(trades) >= 20:
                            tdf = pd.DataFrame(trades)
                            w = (tdf['win'] == True).sum()
                            l_cnt = (tdf['win'] == False).sum()
                            wr = w / len(tdf) * 100
                            pnl = tdf['pnl'].sum()
                            gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
                            gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
                            pf = gp / (gl if gl > 0 else 1.0)

                            daily = tdf.groupby('date').agg(
                                trades=('win', 'count'),
                                wins=('win', lambda x: (x == True).sum()),
                                losses=('win', lambda x: (x == False).sum()),
                                dpnl=('pnl', 'sum')
                            )
                            green_days = (daily['dpnl'] > 0).sum()
                            red_days = (daily['dpnl'] < 0).sum()
                            d_wr = green_days / len(daily) * 100

                            results.append({
                                'be_trig': be_trigger,
                                'sl_mult': sl_mult,
                                'trend': use_trend,
                                'breaker': use_circuit_breaker,
                                'wick': use_wick,
                                'trades': len(tdf),
                                'wr': wr,
                                'wins': w,
                                'losses': l_cnt,
                                'pf': pf,
                                'pnl': pnl,
                                'g_days': green_days,
                                'r_days': red_days,
                                'd_wr': d_wr,
                                'avg_trades_day': len(tdf) / len(daily)
                            })

    rdf = pd.DataFrame(results)
    # Filter for configurations where Daily Win Rate >= 70% and Profit Factor >= 1.40
    filtered = rdf[(rdf['d_wr'] >= 70.0) & (rdf['pf'] >= 1.30)].sort_values(by=['d_wr', 'pf', 'pnl'], ascending=[False, False, False])

    print(f"Total configurations tested: {len(rdf)}")
    print(f"\nTOP CONFIGURATIONS WHERE PROFITS CONSISTENTLY EAT LOSSES (Daily Win Rate >= 70% & PF >= 1.3):")
    if len(filtered) > 0:
        print(filtered.head(10).to_string(index=False))
    else:
        print(rdf.sort_values(by=['d_wr', 'pf'], ascending=[False, False]).head(10).to_string(index=False))

if __name__ == "__main__":
    run_silver_deep_search()
