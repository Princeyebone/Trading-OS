import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def test_daily_high_winrate_options():
    if not mt5.initialize():
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 4000)
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

    df['date'] = df['time'].dt.date
    df['hour'] = df['time'].dt.hour

    lot_size = 0.05
    mult = 5000 * lot_size

    # OPTION A: London Opening Breakout (08:00 - 10:00 UTC) with 1.0 R:R or 1.2 R:R
    # Max 1 trade per day
    trades_orb = []
    days = df['date'].unique()
    for d in days:
        day_df = df[df['date'] == d]
        pre_london = day_df[(day_df['hour'] >= 5) & (day_df['hour'] < 8)]
        if len(pre_london) < 2:
            continue
        high_lvl = pre_london['high'].max()
        low_lvl = pre_london['low'].min()
        rng = high_lvl - low_lvl
        if rng < 0.10: # avoid ultra flat pre-market
            continue

        session_df = day_df[(day_df['hour'] >= 8) & (day_df['hour'] <= 13)]
        for idx, s_row in session_df.iterrows():
            pos_idx = df.index.get_loc(idx)
            # Long
            if s_row['close'] > high_lvl:
                entry = s_row['close']
                atr = s_row['atr']
                sl = entry - (1.0 * atr)
                tp = entry + (1.5 * atr)
                for k in range(pos_idx + 1, min(pos_idx + 18, len(df))):
                    f_bar = df.iloc[k]
                    if f_bar['low'] <= sl:
                        trades_orb.append({'date': d, 'win': False, 'pnl': (sl - entry) * mult})
                        break
                    elif f_bar['high'] >= tp:
                        trades_orb.append({'date': d, 'win': True, 'pnl': (tp - entry) * mult})
                        break
                break
            # Short
            elif s_row['close'] < low_lvl:
                entry = s_row['close']
                atr = s_row['atr']
                sl = entry + (1.0 * atr)
                tp = entry - (1.5 * atr)
                for k in range(pos_idx + 1, min(pos_idx + 18, len(df))):
                    f_bar = df.iloc[k]
                    if f_bar['high'] >= sl:
                        trades_orb.append({'date': d, 'win': False, 'pnl': (entry - sl) * mult})
                        break
                    elif f_bar['low'] <= tp:
                        trades_orb.append({'date': d, 'win': True, 'pnl': (entry - tp) * mult})
                        break
                break

    # OPTION B: NY Session Mean Reversion Sniper (13:00 - 17:00 UTC)
    # When London pushes Silver into extremes (RSI < 30 or > 70), take 1 reversal trade into NY session
    trades_ny_rev = []
    daily_traded_ny = set()
    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        cur_date = row['date']
        cur_hour = row['hour']

        if cur_date in daily_traded_ny:
            continue
        if not (12 <= cur_hour <= 16):
            continue

        # Oversold Bounce
        if prev['rsi'] < 30 and prev['close'] > prev['open']:
            entry = row['open']
            sl = entry - (1.0 * prev['atr'])
            tp = entry + (1.5 * prev['atr'])
            for j in range(i, min(i + 16, len(df))):
                f_bar = df.iloc[j]
                if f_bar['low'] <= sl:
                    trades_ny_rev.append({'date': cur_date, 'win': False, 'pnl': (sl - entry) * mult})
                    daily_traded_ny.add(cur_date)
                    break
                elif f_bar['high'] >= tp:
                    trades_ny_rev.append({'date': cur_date, 'win': True, 'pnl': (tp - entry) * mult})
                    daily_traded_ny.add(cur_date)
                    break

        # Overbought Fade
        elif prev['rsi'] > 70 and prev['close'] < prev['open']:
            entry = row['open']
            sl = entry + (1.0 * prev['atr'])
            tp = entry - (1.5 * prev['atr'])
            for j in range(i, min(i + 16, len(df))):
                f_bar = df.iloc[j]
                if f_bar['high'] >= sl:
                    trades_ny_rev.append({'date': cur_date, 'win': False, 'pnl': (entry - sl) * mult})
                    daily_traded_ny.add(cur_date)
                    break
                elif f_bar['low'] <= tp:
                    trades_ny_rev.append({'date': cur_date, 'win': True, 'pnl': (entry - tp) * mult})
                    daily_traded_ny.add(cur_date)
                    break

    def print_res(td, name):
        tdf = pd.DataFrame(td)
        print(f"\n{name}:")
        if len(tdf) == 0:
            print("No trades")
            return
        wins = tdf[tdf['win'] == True]
        losses = tdf[tdf['win'] == False]
        wr = len(wins) / len(tdf) * 100
        pnl = tdf['pnl'].sum()
        gp = wins['pnl'].sum()
        gl = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
        pf = gp / gl
        print(f"  Days Traded (1 Trade/Day Max): {len(tdf)}")
        print(f"  Win Rate                     : {wr:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"  Profit Factor                : {pf:.2f}")
        print(f"  Net PnL (0.05 Lot)           : +${pnl:,.2f}")
        print(f"  Avg Win / Loss               : +${wins['pnl'].mean():.2f} / -${abs(losses['pnl'].mean()):.2f}")

    print_res(trades_orb, "OPTION A: London Opening Breakout Sniper (Max 1 Trade/Day)")
    print_res(trades_ny_rev, "OPTION B: NY Session Exhaustion Fade (Max 1 Trade/Day)")

test_daily_high_winrate_options()
