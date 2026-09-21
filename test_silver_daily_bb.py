import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def test_daily_bb_reversion_exact_one():
    if not mt5.initialize():
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 3000)
    mt5.shutdown()

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    c = df['close']
    h = df['high']
    l = df['low']

    # ATR(14)
    tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    # Bollinger Bands (20, 2.0)
    df['bb_mid'] = c.rolling(20).mean()
    df['bb_std'] = c.rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.0 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2.0 * df['bb_std']

    df['date'] = df['time'].dt.date
    lot_size = 0.05
    mult = 5000 * lot_size

    # STRICT RULE: ONLY 1 TRADE PER DAY ALLOWED.
    # Take the first clean rejection back inside the Bollinger Bands of each day.
    # TP at bb_mid (the exact mean reversion mechanism), SL at 1.5 ATR.
    trades_one_a_day = []
    traded_dates = set()

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        cur_date = row['date']

        if cur_date in traded_dates:
            continue

        # Long trigger: previous candle dipped below lower band, closed back inside
        if prev2['close'] < prev2['bb_lower'] and prev['close'] >= prev['bb_lower']:
            entry = row['open']
            sl = entry - (1.5 * prev['atr'])
            tp = prev['bb_mid']
            entry_time = row['time']

            if tp > entry:
                for j in range(i, min(i + 48, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['low'] <= sl:
                        trades_one_a_day.append({
                            'date': cur_date,
                            'time': entry_time,
                            'dir': 'LONG',
                            'win': False,
                            'pnl': (sl - entry) * mult
                        })
                        traded_dates.add(cur_date)
                        break
                    elif f_bar['high'] >= tp:
                        trades_one_a_day.append({
                            'date': cur_date,
                            'time': entry_time,
                            'dir': 'LONG',
                            'win': True,
                            'pnl': (tp - entry) * mult
                        })
                        traded_dates.add(cur_date)
                        break

        # Short trigger: previous candle poked above upper band, closed back inside
        elif prev2['close'] > prev2['bb_upper'] and prev['close'] <= prev['bb_upper']:
            entry = row['open']
            sl = entry + (1.5 * prev['atr'])
            tp = prev['bb_mid']
            entry_time = row['time']

            if tp < entry:
                for j in range(i, min(i + 48, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['high'] >= sl:
                        trades_one_a_day.append({
                            'date': cur_date,
                            'time': entry_time,
                            'dir': 'SHORT',
                            'win': False,
                            'pnl': (entry - sl) * mult
                        })
                        traded_dates.add(cur_date)
                        break
                    elif f_bar['low'] <= tp:
                        trades_one_a_day.append({
                            'date': cur_date,
                            'time': entry_time,
                            'dir': 'SHORT',
                            'win': True,
                            'pnl': (entry - tp) * mult
                        })
                        traded_dates.add(cur_date)
                        break

    tdf = pd.DataFrame(trades_one_a_day)
    wins = tdf[tdf['win'] == True]
    losses = tdf[tdf['win'] == False]
    wr = len(wins) / len(tdf) * 100
    pnl = tdf['pnl'].sum()
    gp = wins['pnl'].sum()
    gl = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = gp / gl

    print("=" * 70)
    print("  EXACT 1-TRADE-PER-DAY BOLLINGER BAND REVERSION ON SILVER (XAGUSD)")
    print("=" * 70)
    print(f"Total Trading Days in Period    : 134 days")
    print(f"Days a Trade Was Fired          : {len(tdf)} days ({len(tdf)/134*100:.1f}% participation)")
    print(f"Win Rate (Strict 1 Trade/Day)   : {wr:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"Profit Factor                   : {pf:.2f}")
    print(f"Net Profit (0.05 Lot)           : +${pnl:,.2f}")
    print(f"Average Win Size                : +${wins['pnl'].mean():.2f}")
    print(f"Average Loss Size               : -${abs(losses['pnl'].mean()):.2f}")

    print("\nRecent 15 Trades (Chronological):")
    for _, r in tdf.tail(15).iterrows():
        print(f"  {r['date']} | {r['dir']:5} | PnL: ${r['pnl']:+8.2f} | {'WIN ' if r['win'] else 'LOSS'}")

test_daily_bb_reversion_exact_one()
