import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_hyper_search():
    if not mt5.initialize():
        print("Failed to init MT5")
        return

    # Fetch high-resolution M5 candle data (last 10,000 M5 candles ~ 5-6 weeks)
    rates_m5 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M5, 0, 12000)
    mt5.shutdown()

    if rates_m5 is None or len(rates_m5) == 0:
        print("No rates returned")
        return

    df = pd.DataFrame(rates_m5)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour
    c = df['close']
    h = df['high']
    l = df['low']

    # ATR(14) on M5
    tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    # RSI(14)
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    # Grid search parameters:
    # 1. BB deviation: [2.0, 2.2, 2.5]
    # 2. RSI threshold: [(35, 65), (30, 70), (25, 75)]
    # 3. TP: [bb_mid, bb_mid * 0.8]
    # 4. SL multiplier on ATR: [1.2, 1.5, 2.0]
    # 5. Trend Filter (EMA 50 / 200) or No Trend Filter

    lot_size = 0.05
    mult = 5000 * lot_size # $250 per $1.00 move

    print(f"Data range: {df['time'].min()} to {df['time'].max()} ({len(df['date'].unique())} trading days, {len(df)} M5 bars)")

    best_results = []

    for dev in [2.0, 2.2, 2.4]:
        df['bb_mid'] = c.rolling(20).mean()
        df['bb_std'] = c.rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + dev * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - dev * df['bb_std']

        for rsi_low, rsi_high in [(40, 60), (35, 65), (30, 70)]:
            for sl_mult in [1.2, 1.5, 2.0]:
                for filter_trend in [False, True]:
                    # EMA 100 for trend filter
                    if filter_trend and 'ema100' not in df:
                        df['ema100'] = c.ewm(span=100, adjust=False).mean()

                    trades = []
                    in_pos = False
                    pos_exit_idx = 0

                    for i in range(30, len(df)):
                        if i < pos_exit_idx:
                            continue

                        prev = df.iloc[i-1]
                        prev2 = df.iloc[i-2]
                        row = df.iloc[i]

                        # Long Condition: Mean reversion snap-back
                        # Candle closed below lower band or touched it with RSI oversold, now snapping back
                        long_sig = (prev2['close'] < prev2['bb_lower'] or prev['close'] < prev['bb_lower']) and prev['rsi'] < rsi_low
                        if filter_trend:
                            long_sig = long_sig and (prev['close'] > prev['ema100']) # buy dips in uptrend

                        short_sig = (prev2['close'] > prev2['bb_upper'] or prev['close'] > prev['bb_upper']) and prev['rsi'] > rsi_high
                        if filter_trend:
                            short_sig = short_sig and (prev['close'] < prev['ema100']) # sell rips in downtrend

                        if long_sig:
                            entry = row['open']
                            tp = prev['bb_mid']
                            if tp <= entry + 0.02: # ensure min profit
                                continue
                            sl = entry - (sl_mult * prev['atr'])
                            # forward sim
                            for j in range(i, min(i + 40, len(df))):
                                f_bar = df.iloc[j]
                                if f_bar['low'] <= sl:
                                    trades.append({'date': row['date'], 'win': False, 'pnl': (sl - entry) * mult})
                                    pos_exit_idx = j + 1
                                    break
                                elif f_bar['high'] >= tp:
                                    trades.append({'date': row['date'], 'win': True, 'pnl': (tp - entry) * mult})
                                    pos_exit_idx = j + 1
                                    break

                        elif short_sig:
                            entry = row['open']
                            tp = prev['bb_mid']
                            if tp >= entry - 0.02:
                                continue
                            sl = entry + (sl_mult * prev['atr'])
                            for j in range(i, min(i + 40, len(df))):
                                f_bar = df.iloc[j]
                                if f_bar['high'] >= sl:
                                    trades.append({'date': row['date'], 'win': False, 'pnl': (entry - sl) * mult})
                                    pos_exit_idx = j + 1
                                    break
                                elif f_bar['low'] <= tp:
                                    trades.append({'date': row['date'], 'win': True, 'pnl': (entry - tp) * mult})
                                    pos_exit_idx = j + 1
                                    break

                    if len(trades) >= 20:
                        tdf = pd.DataFrame(trades)
                        wins = tdf[tdf['win'] == True]
                        losses = tdf[tdf['win'] == False]
                        wr = len(wins) / len(tdf) * 100
                        pnl = tdf['pnl'].sum()
                        gp = wins['pnl'].sum()
                        gl = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
                        pf = gp / gl

                        # Daily consistency
                        daily = tdf.groupby('date').agg(
                            cnt=('win', 'count'),
                            w=('win', lambda x: (x == True).sum()),
                            l=('win', lambda x: (x == False).sum()),
                            dpnl=('pnl', 'sum')
                        )
                        green_days = (daily['dpnl'] > 0).sum()
                        total_act_days = len(daily)
                        day_wr = green_days / total_act_days * 100

                        best_results.append({
                            'dev': dev,
                            'rsi': f"{rsi_low}/{rsi_high}",
                            'sl_mult': sl_mult,
                            'trend': filter_trend,
                            'trades': len(tdf),
                            'wr': wr,
                            'pf': pf,
                            'pnl': pnl,
                            'day_wr': day_wr,
                            'act_days': total_act_days,
                            'green_days': green_days,
                            'trades_per_day': len(tdf) / total_act_days
                        })

    res_df = pd.DataFrame(best_results)
    # Sort by highest win rate and profit factor
    res_df = res_df.sort_values(by=['wr', 'pf'], ascending=[False, False])

    print("\nTOP 8 CONFIGURATIONS SORTED BY WIN RATE (Wins Outnumber Losses):")
    print(res_df.head(8).to_string(index=False))

if __name__ == "__main__":
    run_silver_hyper_search()
