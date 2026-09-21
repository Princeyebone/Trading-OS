import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def test_daily_high_probability_sniper():
    if not mt5.initialize():
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 3500)
    mt5.shutdown()

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    c = df['close']
    h = df['high']
    l = df['low']

    # ATR
    tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['ema20'] = c.ewm(span=20, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    
    # RSI
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    df['hour'] = df['time'].dt.hour
    df['date'] = df['time'].dt.date

    lot_size = 0.05
    mult = 5000 * lot_size

    # Let's test a Session-Specific London/NY Momentum Pullback
    # Rule: Once London opens (07:00-14:00 UTC), if trend is active, take the 1st clean retracement to EMA20/50.
    # Take profit at 1.0 ATR or 1.2 ATR, SL at 1.0 ATR (Fast exit for high win rate).
    trades = []
    traded_dates = set()

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        cur_date = row['date']
        cur_hour = row['hour']

        if cur_date in traded_dates:
            continue

        if not (7 <= cur_hour <= 15):
            continue

        # Bullish regime: EMA 50 > EMA 200, and previous bar touched or dipped near EMA 20
        if prev['close'] > prev['ema50'] and prev['ema50'] > prev['ema200']:
            # Pullback to EMA20 and bounce: low was below or near EMA20, close is green and above EMA20
            if prev['low'] <= prev['ema20'] * 1.002 and prev['close'] > prev['open']:
                entry = row['open']
                sl = entry - (1.0 * prev['atr'])
                tp = entry + (1.2 * prev['atr'])
                for j in range(i, min(i + 24, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['low'] <= sl:
                        trades.append({'date': cur_date, 'time': row['time'], 'dir': 'LONG', 'pnl': (sl - entry) * mult, 'win': False})
                        traded_dates.add(cur_date)
                        break
                    elif f_bar['high'] >= tp:
                        trades.append({'date': cur_date, 'time': row['time'], 'dir': 'LONG', 'pnl': (tp - entry) * mult, 'win': True})
                        traded_dates.add(cur_date)
                        break

        # Bearish regime: EMA 50 < EMA 200, and previous bar touched or rallied near EMA 20
        elif prev['close'] < prev['ema50'] and prev['ema50'] < prev['ema200']:
            if prev['high'] >= prev['ema20'] * 0.998 and prev['close'] < prev['open']:
                entry = row['open']
                sl = entry + (1.0 * prev['atr'])
                tp = entry - (1.2 * prev['atr'])
                for j in range(i, min(i + 24, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['high'] >= sl:
                        trades.append({'date': cur_date, 'time': row['time'], 'dir': 'SHORT', 'pnl': (entry - sl) * mult, 'win': False})
                        traded_dates.add(cur_date)
                        break
                    elif f_bar['low'] <= tp:
                        trades.append({'date': cur_date, 'time': row['time'], 'dir': 'SHORT', 'pnl': (entry - tp) * mult, 'win': True})
                        traded_dates.add(cur_date)
                        break

    tdf = pd.DataFrame(trades)
    print(f"\n{'='*70}\n  SILVER DAILY 1-TRADE SNIPER (EMA20 Touch in Trend Session)\n{'='*70}")
    wins = tdf[tdf['win'] == True]
    losses = tdf[tdf['win'] == False]
    wr = len(wins) / len(tdf) * 100
    pnl = tdf['pnl'].sum()
    gp = wins['pnl'].sum()
    gl = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = gp / gl
    print(f"Total Days Traded (Exactly 1 Trade/Day): {len(tdf)} of 134 days ({len(tdf)/134*100:.1f}%)")
    print(f"Win Rate                               : {wr:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"Profit Factor                          : {pf:.2f}")
    print(f"Net Profit (0.05 Lot)                  : +${pnl:,.2f}")
    print(f"Avg Win                                : +${wins['pnl'].mean():.2f}")
    print(f"Avg Loss                               : -${abs(losses['pnl'].mean()):.2f}")

    # Show last 10 trades
    print("\nRecent 10 Trades:")
    for _, r in tdf.tail(10).iterrows():
        print(f"  {r['date']} | {r['dir']} | PnL: ${r['pnl']:+7.2f} | {'WIN' if r['win'] else 'LOSS'}")

test_daily_high_probability_sniper()
