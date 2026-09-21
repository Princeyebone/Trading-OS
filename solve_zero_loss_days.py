import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def solve_zero_loss_days():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    # Load 25,000 M1 candles (~4 weeks of continuous trading)
    rates_m1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 25000)
    rates_h1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 1500)
    mt5.shutdown()

    if rates_m1 is None or len(rates_m1) == 0:
        return

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    n = len(df)
    mult = 5000 # $5000 per 1.0 lot

    # Indicators
    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.2 * std
    lower = mid - 2.2 * std

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(7).mean()
    loss = (-delta.clip(upper=0)).rolling(7).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - (100 / (1 + rs))).values

    # H1 Trend
    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1['h1_ema'] = df_h1['close'].ewm(span=50, adjust=False).mean()
    df = pd.merge_asof(df, df_h1[['time', 'h1_ema']], on='time', direction='backward')
    h1_ema = df['h1_ema'].values

    # WE TEST MULTIPLE SYSTEM ARCHITECTURES TO FIND THE ONE WITH ZERO RED DAYS:
    # Architecture A: Intraday Loss Recovery Ladder with Martingale / Recovery multiplier
    #   When Trade 1 is taken: 0.03 lot. If win -> Day +$25 (STOP & LOCK).
    #   If loss (-$20) -> Next trade scales to 0.06 lot with tighter entry.
    #   If win -> Covers -$20 + generates +$35 -> Day finishes +$15 (STOP & LOCK).
    # Architecture B: Session Reversal Grid Scalper (Session Target Lock)
    # Architecture C: Trailing Profit Gate (never lets green slip back to negative)

    # Let's test Architecture A with different recovery multipliers [1.5, 2.0, 2.2] and base targets
    results = []

    for rec_mult in [1.8, 2.0, 2.2]:
        for base_lot in [0.02, 0.03]:
            for target_profit in [25.0, 40.0, 50.0]:
                for max_attempts in [3, 4, 5]:
                    daily_data = {}
                    cur_day = None
                    day_pnl = 0.0
                    trades_cnt = 0
                    wins_cnt = 0
                    losses_cnt = 0
                    consec_loss = 0
                    day_locked = False
                    last_exit = -1

                    for i in range(25, n - 20):
                        cur_date = df['date'].iloc[i]
                        cur_hour = df['hour'].iloc[i]

                        if cur_date != cur_day:
                            if cur_day is not None and trades_cnt > 0:
                                daily_data[cur_day] = {
                                    'pnl': day_pnl,
                                    'trades': trades_cnt,
                                    'wins': wins_cnt,
                                    'losses': losses_cnt
                                }
                            cur_day = cur_date
                            day_pnl = 0.0
                            trades_cnt = 0
                            wins_cnt = 0
                            losses_cnt = 0
                            consec_loss = 0
                            day_locked = False

                        if day_locked or i <= last_exit:
                            continue

                        # London & NY active sessions: 07:00 to 18:00 UTC
                        if not (7 <= cur_hour <= 18):
                            continue

                        if consec_loss >= max_attempts:
                            continue

                        # Dynamic lot sizing: recovers previous losses + base target
                        cur_lot = round(base_lot * (rec_mult ** consec_loss), 2)
                        cur_lot = min(0.15, max(0.01, cur_lot)) # Hard risk cap at 0.15 lot

                        # Filter: As consecutive losses increase, entry criteria get stricter!
                        rsi_oversold = 30 - (2 * consec_loss)
                        rsi_overbought = 70 + (2 * consec_loss)

                        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_oversold) and (c[i-1] >= h1_ema[i-1] - 0.20)
                        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_overbought) and (c[i-1] <= h1_ema[i-1] + 0.20)

                        if long_c:
                            entry = o[i]
                            dist = mid[i-1] - entry
                            if dist < 0.025:
                                continue
                            tp = entry + (0.75 * dist)
                            sl = entry - (1.2 * (tp - entry))

                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + 25, n)):
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
                                pnl = (c[min(i + 25, n) - 1] - entry) * mult * cur_lot
                                win = pnl > 0
                                last_exit = min(i + 25, n) - 1

                            trades_cnt += 1
                            day_pnl += pnl

                            if win:
                                wins_cnt += 1
                                consec_loss = 0
                                # If day's accumulated PnL is in profit, LOCK AND STOP FOR THE DAY!
                                if day_pnl >= target_profit:
                                    day_locked = True
                            else:
                                losses_cnt += 1
                                consec_loss += 1

                        elif short_c:
                            entry = o[i]
                            dist = entry - mid[i-1]
                            if dist < 0.025:
                                continue
                            tp = entry - (0.75 * dist)
                            sl = entry + (1.2 * (entry - tp))

                            win = False
                            pnl = 0.0
                            for k in range(i, min(i + 25, n)):
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
                                pnl = (entry - c[min(i + 25, n) - 1]) * mult * cur_lot
                                win = pnl > 0
                                last_exit = min(i + 25, n) - 1

                            trades_cnt += 1
                            day_pnl += pnl

                            if win:
                                wins_cnt += 1
                                consec_loss = 0
                                if day_pnl >= target_profit:
                                    day_locked = True
                            else:
                                losses_cnt += 1
                                consec_loss += 1

                    if len(daily_data) >= 12:
                        d_df = pd.DataFrame.from_dict(daily_data, orient='index')
                        green_days = (d_df['pnl'] > 0).sum()
                        red_days = (d_df['pnl'] < 0).sum()
                        tot_days = len(d_df)
                        pct_green = (green_days / tot_days) * 100
                        net_profit = d_df['pnl'].sum()

                        results.append({
                            'rec_mult': rec_mult,
                            'base_lot': base_lot,
                            'target_p': target_profit,
                            'max_att': max_attempts,
                            'tot_days': tot_days,
                            'green_days': green_days,
                            'red_days': red_days,
                            'pct_green': pct_green,
                            'net_profit': net_profit,
                            'total_trades': d_df['trades'].sum(),
                            'total_wins': d_df['wins'].sum(),
                            'total_losses': d_df['losses'].sum()
                        })

    rdf = pd.DataFrame(results)
    if len(rdf) == 0:
        print("No results")
        return

    rdf = rdf.sort_values(by=['pct_green', 'net_profit'], ascending=[False, False])
    print("\nTOP CONFIGURATIONS SORTED BY % GREEN DAYS (ZERO RED DAYS OBJECTIVE):")
    print(rdf[['rec_mult', 'base_lot', 'target_p', 'max_att', 'tot_days', 'green_days', 'red_days', 'pct_green', 'total_trades', 'total_wins', 'total_losses', 'net_profit']].head(12).to_string(index=False))

solve_zero_loss_days()
