import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def test_single_daily_sniper():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 3500)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print("No rates returned")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    c = df['close']
    h = df['high']
    l = df['low']
    o = df['open']

    # Indicators
    tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    
    # RSI
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    # Bollinger Bands (20, 2.2) - wider bands for high probability extremes
    df['bb_mid'] = c.rolling(20).mean()
    df['bb_std'] = c.rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.2 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2.2 * df['bb_std']

    df['hour'] = df['time'].dt.hour
    df['date'] = df['time'].dt.date

    lot_size = 0.05
    mult = 5000 * lot_size # $250 / $1.00 move

    # MODEL 1: London/NY Session Trend Pullback (Max 1 trade per day)
    # Trading window: 07:00 to 16:00 UTC (Active European + US volume)
    # Rule: Price aligned with EMA50 & EMA200 (strong trend). RSI dips into 38-48 zone for Long, 52-62 zone for Short.
    trades_m1 = []
    daily_traded_m1 = set()

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        cur_date = row['date']
        cur_hour = row['hour']

        if cur_date in daily_traded_m1:
            continue

        # Only search for setup during high-volume sessions (07:00 - 15:00 broker time)
        if not (7 <= cur_hour <= 15):
            continue

        # Strong Bullish Trend: Close > EMA50 > EMA200
        if prev['close'] > prev['ema50'] and prev['ema50'] > prev['ema200']:
            # Pullback trigger: RSI crossed above 42
            if prev['rsi'] > 42 and prev2['rsi'] <= 42:
                entry = row['open']
                sl = entry - (1.0 * prev['atr'])
                tp = entry + (1.5 * prev['atr'])
                # simulate
                for j in range(i, min(i + 24, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['low'] <= sl:
                        trades_m1.append({'date': cur_date, 'time': row['time'], 'dir': 'LONG', 'pnl': (sl - entry) * mult, 'win': False})
                        daily_traded_m1.add(cur_date)
                        break
                    elif f_bar['high'] >= tp:
                        trades_m1.append({'date': cur_date, 'time': row['time'], 'dir': 'LONG', 'pnl': (tp - entry) * mult, 'win': True})
                        daily_traded_m1.add(cur_date)
                        break

        # Strong Bearish Trend: Close < EMA50 < EMA200
        elif prev['close'] < prev['ema50'] and prev['ema50'] < prev['ema200']:
            # Pullback trigger: RSI crossed below 58
            if prev['rsi'] < 58 and prev2['rsi'] >= 58:
                entry = row['open']
                sl = entry + (1.0 * prev['atr'])
                tp = entry - (1.5 * prev['atr'])
                for j in range(i, min(i + 24, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['high'] >= sl:
                        trades_m1.append({'date': cur_date, 'time': row['time'], 'dir': 'SHORT', 'pnl': (entry - sl) * mult, 'win': False})
                        daily_traded_m1.add(cur_date)
                        break
                    elif f_bar['low'] <= tp:
                        trades_m1.append({'date': cur_date, 'time': row['time'], 'dir': 'SHORT', 'pnl': (entry - tp) * mult, 'win': True})
                        daily_traded_m1.add(cur_date)
                        break

    # MODEL 2: Silver Daily Extreme Reversion (Max 1 trade per day)
    # Band deviation 2.2, RSI < 32 or > 68 (Hyper-selective mean reversion)
    trades_m2 = []
    daily_traded_m2 = set()

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        cur_date = row['date']
        cur_hour = row['hour']

        if cur_date in daily_traded_m2:
            continue

        if not (6 <= cur_hour <= 18):
            continue

        # Long: Price breached lower BB (2.2) and RSI oversold (< 32), then bounced back
        if prev['low'] < prev['bb_lower'] and prev['close'] >= prev['bb_lower'] and prev['rsi'] < 35:
            entry = row['open']
            sl = entry - (1.0 * prev['atr'])
            tp = entry + (1.5 * prev['atr'])
            for j in range(i, min(i + 24, len(df))):
                f_bar = df.iloc[j]
                if f_bar['low'] <= sl:
                    trades_m2.append({'date': cur_date, 'time': row['time'], 'dir': 'LONG', 'pnl': (sl - entry) * mult, 'win': False})
                    daily_traded_m2.add(cur_date)
                    break
                elif f_bar['high'] >= tp:
                    trades_m2.append({'date': cur_date, 'time': row['time'], 'dir': 'LONG', 'pnl': (tp - entry) * mult, 'win': True})
                    daily_traded_m2.add(cur_date)
                    break

        # Short: Price breached upper BB (2.2) and RSI overbought (> 68), then rejected back
        elif prev['high'] > prev['bb_upper'] and prev['close'] <= prev['bb_upper'] and prev['rsi'] > 65:
            entry = row['open']
            sl = entry + (1.0 * prev['atr'])
            tp = entry - (1.5 * prev['atr'])
            for j in range(i, min(i + 24, len(df))):
                f_bar = df.iloc[j]
                if f_bar['high'] >= sl:
                    trades_m2.append({'date': cur_date, 'time': row['time'], 'dir': 'SHORT', 'pnl': (entry - sl) * mult, 'win': False})
                    daily_traded_m2.add(cur_date)
                    break
                elif f_bar['low'] <= tp:
                    trades_m2.append({'date': cur_date, 'time': row['time'], 'dir': 'SHORT', 'pnl': (entry - tp) * mult, 'win': True})
                    daily_traded_m2.add(cur_date)
                    break

    # MODEL 3: London Opening Range Breakout (ORB) on Silver
    # Define range between 06:00 and 08:00 UTC. Breakout between 08:00 and 13:00.
    trades_m3 = []
    # Let's test
    days = df['date'].unique()
    for d in days:
        day_df = df[df['date'] == d]
        pre_london = day_df[(day_df['hour'] >= 6) & (day_df['hour'] < 8)]
        if len(pre_london) < 2:
            continue
        high_lvl = pre_london['high'].max()
        low_lvl = pre_london['low'].min()
        rng = high_lvl - low_lvl
        if rng == 0:
            continue

        session_df = day_df[(day_df['hour'] >= 8) & (day_df['hour'] <= 14)]
        if len(session_df) == 0:
            continue

        # Look for first breakout
        for idx, s_row in session_df.iterrows():
            # Long breakout
            if s_row['close'] > high_lvl:
                entry = s_row['close']
                sl = low_lvl
                tp = entry + (high_lvl - low_lvl) * 1.5
                # simulate
                pos_idx = df.index.get_loc(idx)
                for k in range(pos_idx + 1, min(pos_idx + 20, len(df))):
                    f_bar = df.iloc[k]
                    if f_bar['low'] <= sl:
                        trades_m3.append({'date': d, 'dir': 'LONG', 'pnl': (sl - entry) * mult, 'win': False})
                        break
                    elif f_bar['high'] >= tp:
                        trades_m3.append({'date': d, 'dir': 'LONG', 'pnl': (tp - entry) * mult, 'win': True})
                        break
                break # Only 1 trade per day
            elif s_row['close'] < low_lvl:
                entry = s_row['close']
                sl = high_lvl
                tp = entry - (high_lvl - low_lvl) * 1.5
                pos_idx = df.index.get_loc(idx)
                for k in range(pos_idx + 1, min(pos_idx + 20, len(df))):
                    f_bar = df.iloc[k]
                    if f_bar['high'] >= sl:
                        trades_m3.append({'date': d, 'dir': 'SHORT', 'pnl': (entry - sl) * mult, 'win': False})
                        break
                    elif f_bar['low'] <= tp:
                        trades_m3.append({'date': d, 'dir': 'SHORT', 'pnl': (entry - tp) * mult, 'win': True})
                        break
                break

    def print_sniper(trades, title):
        tdf = pd.DataFrame(trades)
        print(f"\n{'='*70}\n  {title}\n{'='*70}")
        if len(tdf) == 0:
            print("No trades triggered.")
            return
        wins = tdf[tdf['win'] == True]
        losses = tdf[tdf['win'] == False]
        wr = len(wins) / len(tdf) * 100
        pnl = tdf['pnl'].sum()
        gp = wins['pnl'].sum()
        gl = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
        pf = gp / gl
        print(f"Total Trades (1 per day max): {len(tdf)}")
        print(f"Win Rate                    : {wr:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"Profit Factor               : {pf:.2f}")
        print(f"Total Net PnL (0.05 lot)    : +${pnl:,.2f}")
        print(f"Avg Win Size                : +${wins['pnl'].mean():.2f}")
        print(f"Avg Loss Size               : -${abs(losses['pnl'].mean()):.2f}")

    print_sniper(trades_m1, "MODEL 1: Dual-EMA Trend Pullback Sniper (Max 1 Trade/Day)")
    print_sniper(trades_m2, "MODEL 2: Extreme Bollinger Reversion Sniper (Max 1 Trade/Day)")
    print_sniper(trades_m3, "MODEL 3: London Opening Breakout Sniper (Max 1 Trade/Day)")

if __name__ == "__main__":
    test_single_daily_sniper()
