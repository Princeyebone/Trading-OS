import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def search_high_frequency_silver():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    # Fetch last 20,000 M1 candles (~15-18 trading days of granular 1-minute data)
    rates_m1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 20000)
    mt5.shutdown()

    if rates_m1 is None or len(rates_m1) == 0:
        print("No rates returned")
        return

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    n = len(df)
    lot_size = 0.05
    mult = 5000 * lot_size # $250 per $1.00 move

    print(f"Loaded {n} M1 bars from {df['date'].min()} to {df['date'].max()} ({len(df['date'].unique())} days)")

    # Test candidate high-frequency architectures:
    # 1. Micro BB (M1, Window 20, Dev 2.0 to 2.5) with Quick Snap Target (0.4 to 0.7 of distance to mid)
    # 2. Dual EMA Pullback Scalper (EMA 9 / EMA 21 micro-momentum scalper)
    # 3. Micro RSI Reversion (RSI 7 period on M1, extreme 20/80, target fast 5-bar mean)

    best_configs = []

    for bb_dev in [2.0, 2.2, 2.4]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + bb_dev * std
        lower = mid - bb_dev * std

        for rsi_period in [7, 14]:
            delta = pd.Series(c).diff()
            gain = delta.clip(lower=0).rolling(rsi_period).mean()
            loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
            rs = gain / (loss + 1e-9)
            rsi = (100 - (100 / (1 + rs))).values

            for rsi_low, rsi_high in [(30, 70), (25, 75)]:
                for tp_fraction in [0.4, 0.6, 0.8]: # Target fraction towards mid band
                    for sl_mult in [1.5, 2.0]: # SL multiplier
                        trades = []
                        last_exit = -1

                        for i in range(30, n - 20):
                            if i <= last_exit:
                                continue

                            hr = df['hour'].iloc[i]
                            # Active trading sessions: 06:00 to 19:00 UTC
                            if not (6 <= hr <= 19):
                                continue

                            long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < rsi_low)
                            short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > rsi_high)

                            if long_c:
                                entry = o[i]
                                dist_to_mid = mid[i-1] - entry
                                if dist_to_mid < 0.02:
                                    continue
                                tp = entry + (tp_fraction * dist_to_mid)
                                sl = entry - (sl_mult * (tp - entry))

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

                                trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                            elif short_c:
                                entry = o[i]
                                dist_to_mid = entry - mid[i-1]
                                if dist_to_mid < 0.02:
                                    continue
                                tp = entry - (tp_fraction * dist_to_mid)
                                sl = entry + (sl_mult * (entry - tp))

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

                                trades.append({'date': df['date'].iloc[i], 'win': win, 'pnl': pnl})

                        if len(trades) >= 50:
                            tdf = pd.DataFrame(trades)
                            # Daily grouping
                            daily = tdf.groupby('date').agg(
                                cnt=('win', 'count'),
                                w=('win', lambda x: (x == True).sum()),
                                l=('win', lambda x: (x == False).sum()),
                                pnl=('pnl', 'sum')
                            )
                            # Key Metric: Days where Wins > Losses
                            wins_beat_losses_days = (daily['w'] > daily['l']).sum()
                            total_days = len(daily)
                            green_days = (daily['pnl'] > 0).sum()
                            avg_trades = len(tdf) / total_days

                            best_configs.append({
                                'dev': bb_dev,
                                'rsi_p': rsi_period,
                                'rsi_th': f"{rsi_low}/{rsi_high}",
                                'tp_frac': tp_fraction,
                                'sl_m': sl_mult,
                                'trades': len(tdf),
                                'wr': tdf['win'].mean() * 100,
                                'avg_trades_day': avg_trades,
                                'w_gt_l_days': wins_beat_losses_days,
                                'green_days': green_days,
                                'total_days': total_days,
                                'daily_win_consistency': (wins_beat_losses_days / total_days) * 100,
                                'net_pnl': tdf['pnl'].sum()
                            })

    rdf = pd.DataFrame(best_configs)
    if len(rdf) == 0:
        print("No valid configs found.")
        return

    # Sort primarily by: Daily Win Consistency (Days where Wins > Losses), then Total Net PnL
    rdf = rdf.sort_values(by=['daily_win_consistency', 'wr', 'net_pnl'], ascending=[False, False, False])
    print("\n" + "=" * 85)
    print("  TOP 10 CONFIGURATIONS: WINS OUTNUMBER LOSSES EVERY DAY (HIGH FREQUENCY)")
    print("=" * 85)
    print(rdf[['dev', 'rsi_p', 'rsi_th', 'tp_frac', 'sl_m', 'trades', 'avg_trades_day', 'wr', 'w_gt_l_days', 'green_days', 'total_days', 'daily_win_consistency', 'net_pnl']].head(10).to_string(index=False))

search_high_frequency_silver()
