import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def explore_silver():
    if not mt5.initialize():
        return
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 3000)
    mt5.shutdown()
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    c = df['close']
    h = df['high']
    l = df['low']
    
    # ATR
    tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # EMAs
    df['ema20'] = c.ewm(span=20, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    
    # RSI
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands (20, 2.0)
    df['bb_mid'] = c.rolling(20).mean()
    df['bb_std'] = c.rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.0 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2.0 * df['bb_std']

    lot_size = 0.05
    mult = 5000 * lot_size # $250 per $1.00 move

    # TEST A: Trend Pullback (EMA 50 trend, RSI dip to 40/60)
    # Buy when close > ema50 and rsi crosses above 45
    # TP = 2.0 ATR, SL = 1.0 ATR
    trades = []
    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        # Long condition: Uptrend on EMA50, RSI crosses above 45 from oversold
        if prev['close'] > prev['ema50'] and prev['rsi'] > 45 and df.iloc[i-2]['rsi'] <= 45:
            entry = row['open']
            sl = entry - (1.2 * prev['atr'])
            tp = entry + (2.0 * prev['atr'])
            # simulate forward up to 48 bars
            for j in range(i, min(i+48, len(df))):
                f_bar = df.iloc[j]
                if f_bar['low'] <= sl:
                    trades.append({'pnl': (sl - entry) * mult, 'type': 'SL', 'dir': 'LONG'})
                    break
                elif f_bar['high'] >= tp:
                    trades.append({'pnl': (tp - entry) * mult, 'type': 'TP', 'dir': 'LONG'})
                    break

        # Short condition: Downtrend on EMA50, RSI crosses below 55 from overbought
        elif prev['close'] < prev['ema50'] and prev['rsi'] < 55 and df.iloc[i-2]['rsi'] >= 55:
            entry = row['open']
            sl = entry + (1.2 * prev['atr'])
            tp = entry - (2.0 * prev['atr'])
            for j in range(i, min(i+48, len(df))):
                f_bar = df.iloc[j]
                if f_bar['high'] >= sl:
                    trades.append({'pnl': (entry - sl) * mult, 'type': 'SL', 'dir': 'SHORT'})
                    break
                elif f_bar['low'] <= tp:
                    trades.append({'pnl': (entry - tp) * mult, 'type': 'TP', 'dir': 'SHORT'})
                    break

    tdf = pd.DataFrame(trades)
    if len(tdf) > 0:
        wr = len(tdf[tdf['pnl'] > 0]) / len(tdf) * 100
        pnl = tdf['pnl'].sum()
        gp = tdf[tdf['pnl'] > 0]['pnl'].sum()
        gl = abs(tdf[tdf['pnl'] < 0]['pnl'].sum())
        pf = gp / (gl if gl > 0 else 1.0)
        print(f"Trend-Pullback Strategy (0.05 lot): Trades={len(tdf)}, WR={wr:.1f}%, PnL=${pnl:,.2f}, PF={pf:.2f}")

    # TEST B: Mean Reversion / Bollinger Bands on H1
    trades_mr = []
    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        # Long: Price dipped below lower BB and closed back inside
        if df.iloc[i-2]['close'] < df.iloc[i-2]['bb_lower'] and prev['close'] >= prev['bb_lower']:
            entry = row['open']
            sl = entry - (1.5 * prev['atr'])
            tp = prev['bb_mid']
            if tp > entry:
                for j in range(i, min(i+48, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['low'] <= sl:
                        trades_mr.append({'pnl': (sl - entry) * mult, 'type': 'SL'})
                        break
                    elif f_bar['high'] >= tp:
                        trades_mr.append({'pnl': (tp - entry) * mult, 'type': 'TP'})
                        break

        # Short: Price spiked above upper BB and closed back inside
        elif df.iloc[i-2]['close'] > df.iloc[i-2]['bb_upper'] and prev['close'] <= prev['bb_upper']:
            entry = row['open']
            sl = entry + (1.5 * prev['atr'])
            tp = prev['bb_mid']
            if tp < entry:
                for j in range(i, min(i+48, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['high'] >= sl:
                        trades_mr.append({'pnl': (entry - sl) * mult, 'type': 'SL'})
                        break
                    elif f_bar['low'] <= tp:
                        trades_mr.append({'pnl': (entry - tp) * mult, 'type': 'TP'})
                        break

    tdf_mr = pd.DataFrame(trades_mr)
    if len(tdf_mr) > 0:
        wr = len(tdf_mr[tdf_mr['pnl'] > 0]) / len(tdf_mr) * 100
        pnl = tdf_mr['pnl'].sum()
        gp = tdf_mr[tdf_mr['pnl'] > 0]['pnl'].sum()
        gl = abs(tdf_mr[tdf_mr['pnl'] < 0]['pnl'].sum())
        pf = gp / (gl if gl > 0 else 1.0)
        print(f"BB Mean Reversion H1 (0.05 lot): Trades={len(tdf_mr)}, WR={wr:.1f}%, PnL=${pnl:,.2f}, PF={pf:.2f}")

explore_silver()
