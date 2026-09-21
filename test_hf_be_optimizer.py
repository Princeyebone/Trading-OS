import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_hf_be_optimizer():
    if not mt5.initialize():
        return

    rates_m1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 20000)
    mt5.shutdown()

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close'].values; h = df['high'].values; l = df['low'].values; o = df['open'].values
    n = len(df)
    lot_size = 0.05
    mult = 5000 * lot_size

    # Config #4 and #5: BB Dev 2.2 to 2.4, RSI(7) 30/70, Target 0.6 to 0.8 of mid band
    # Now adding: Dynamic Break-Even trigger (+50% to target locks entry at +$0.50 scratch)
    # Testing SL multiplier [1.2, 1.5]
    
    results = []

    for dev in [2.2, 2.4]:
        mid = pd.Series(c).rolling(20).mean().values
        std = pd.Series(c).rolling(20).std().values
        upper = mid + dev * std
        lower = mid - dev * std

        delta = pd.Series(c).diff()
        gain = delta.clip(lower=0).rolling(7).mean()
        loss = (-delta.clip(upper=0)).rolling(7).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).values

        for tp_frac in [0.6, 0.75]:
            for sl_m in [1.2, 1.5]:
                for be_trig in [0.0, 0.45]:
                    trades = []
                    last_exit = -1

                    for i in range(25, n - 20):
                        if i <= last_exit:
                            continue

                        hr = df['hour'].iloc[i]
                        if not (6 <= hr <= 19):
                            continue

                        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 30)
                        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 70)

                        if long_c:
                            entry = o[i]
                            dist_to_mid = mid[i-1] - entry
                            if dist_to_mid < 0.025:
                                continue
                            tp = entry + (tp_frac * dist_to_mid)
                            target_dist = tp - entry
                            sl = entry - (sl_m * target_dist)

                            win = False
                            pnl = 0.0
                            be_active = False

                            for k in range(i, min(i + 20, n)):
                                if be_trig > 0 and not be_active and h[k] >= entry + (be_trig * target_dist):
                                    sl = entry + 0.003 # locked scratch profit
                                    be_active = True

                                if l[k] <= sl:
                                    pnl = (sl - entry) * mult
                                    win = pnl > 0
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
                            if dist_to_mid < 0.025:
                                continue
                            tp = entry - (tp_frac * dist_to_mid)
                            target_dist = entry - tp
                            sl = entry + (sl_m * target_dist)

                            win = False
                            pnl = 0.0
                            be_active = False

                            for k in range(i, min(i + 20, n)):
                                if be_trig > 0 and not be_active and l[k] <= entry - (be_trig * target_dist):
                                    sl = entry - 0.003
                                    be_active = True

                                if h[k] >= sl:
                                    pnl = (entry - sl) * mult
                                    win = pnl > 0
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
                        daily = tdf.groupby('date').agg(
                            trades=('win', 'count'),
                            wins=('win', lambda x: (x == True).sum()),
                            losses=('win', lambda x: (x == False).sum()),
                            pnl=('pnl', 'sum')
                        )
                        w_gt_l = (daily['wins'] > daily['losses']).sum()
                        g_days = (daily['pnl'] > 0).sum()
                        tot_days = len(daily)

                        results.append({
                            'dev': dev,
                            'tp_frac': tp_frac,
                            'sl_m': sl_m,
                            'be': be_trig,
                            'trades': len(tdf),
                            'trades_day': len(tdf) / tot_days,
                            'wr': tdf['win'].mean() * 100,
                            'w_gt_l_days': w_gt_l,
                            'green_days': g_days,
                            'total_days': tot_days,
                            'consistency': (w_gt_l / tot_days) * 100,
                            'pnl': tdf['pnl'].sum()
                        })

    rdf = pd.DataFrame(results).sort_values(by=['consistency', 'green_days', 'pnl'], ascending=[False, False, False])
    print("\nRESULTS WITH BREAK-EVEN SCRATCH PROTECTION:")
    print(rdf.to_string(index=False))

run_silver_hf_be_optimizer()
