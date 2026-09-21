import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_daily_breakdown():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return

    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 3000)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print("No rates returned")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    c = df['close']
    h = df['high']
    l = df['low']

    # ATR(14)
    tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    # EMA 50
    df['ema50'] = c.ewm(span=50, adjust=False).mean()

    # RSI(14)
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
    mult = 5000 * lot_size # $250 per $1.00 move ($2.50 per cent)

    # -------------------------------------------------------------
    # 1. SIMULATE TREND PULLBACK
    # -------------------------------------------------------------
    trades_trend = []
    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]

        # Long: Uptrend (close > EMA50) & RSI crosses above 45 from dip
        if prev['close'] > prev['ema50'] and prev['rsi'] > 45 and prev2['rsi'] <= 45:
            entry = row['open']
            sl = entry - (1.2 * prev['atr'])
            tp = entry + (2.0 * prev['atr'])
            entry_time = row['time']

            for j in range(i, min(i + 48, len(df))):
                f_bar = df.iloc[j]
                if f_bar['low'] <= sl:
                    trades_trend.append({
                        'entry_time': entry_time,
                        'exit_time': f_bar['time'],
                        'date': entry_time.strftime('%Y-%m-%d'),
                        'dir': 'LONG',
                        'pnl': (sl - entry) * mult,
                        'win': False
                    })
                    break
                elif f_bar['high'] >= tp:
                    trades_trend.append({
                        'entry_time': entry_time,
                        'exit_time': f_bar['time'],
                        'date': entry_time.strftime('%Y-%m-%d'),
                        'dir': 'LONG',
                        'pnl': (tp - entry) * mult,
                        'win': True
                    })
                    break

        # Short: Downtrend (close < EMA50) & RSI crosses below 55 from rally
        elif prev['close'] < prev['ema50'] and prev['rsi'] < 55 and prev2['rsi'] >= 55:
            entry = row['open']
            sl = entry + (1.2 * prev['atr'])
            tp = entry - (2.0 * prev['atr'])
            entry_time = row['time']

            for j in range(i, min(i + 48, len(df))):
                f_bar = df.iloc[j]
                if f_bar['high'] >= sl:
                    trades_trend.append({
                        'entry_time': entry_time,
                        'exit_time': f_bar['time'],
                        'date': entry_time.strftime('%Y-%m-%d'),
                        'dir': 'SHORT',
                        'pnl': (entry - sl) * mult,
                        'win': False
                    })
                    break
                elif f_bar['low'] <= tp:
                    trades_trend.append({
                        'entry_time': entry_time,
                        'exit_time': f_bar['time'],
                        'date': entry_time.strftime('%Y-%m-%d'),
                        'dir': 'SHORT',
                        'pnl': (entry - tp) * mult,
                        'win': True
                    })
                    break

    # -------------------------------------------------------------
    # 2. SIMULATE BOLLINGER BAND MEAN REVERSION
    # -------------------------------------------------------------
    trades_bb = []
    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]

        # Long: Price poked below lower band, now back inside
        if prev2['close'] < prev2['bb_lower'] and prev['close'] >= prev['bb_lower']:
            entry = row['open']
            sl = entry - (1.5 * prev['atr'])
            tp = prev['bb_mid']
            entry_time = row['time']

            if tp > entry:
                for j in range(i, min(i + 48, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['low'] <= sl:
                        trades_bb.append({
                            'entry_time': entry_time,
                            'exit_time': f_bar['time'],
                            'date': entry_time.strftime('%Y-%m-%d'),
                            'dir': 'LONG',
                            'pnl': (sl - entry) * mult,
                            'win': False
                        })
                        break
                    elif f_bar['high'] >= tp:
                        trades_bb.append({
                            'entry_time': entry_time,
                            'exit_time': f_bar['time'],
                            'date': entry_time.strftime('%Y-%m-%d'),
                            'dir': 'LONG',
                            'pnl': (tp - entry) * mult,
                            'win': True
                        })
                        break

        # Short: Price poked above upper band, now back inside
        elif prev2['close'] > prev2['bb_upper'] and prev['close'] <= prev['bb_upper']:
            entry = row['open']
            sl = entry + (1.5 * prev['atr'])
            tp = prev['bb_mid']
            entry_time = row['time']

            if tp < entry:
                for j in range(i, min(i + 48, len(df))):
                    f_bar = df.iloc[j]
                    if f_bar['high'] >= sl:
                        trades_bb.append({
                            'entry_time': entry_time,
                            'exit_time': f_bar['time'],
                            'date': entry_time.strftime('%Y-%m-%d'),
                            'dir': 'SHORT',
                            'pnl': (entry - sl) * mult,
                            'win': False
                        })
                        break
                    elif f_bar['low'] <= tp:
                        trades_bb.append({
                            'entry_time': entry_time,
                            'exit_time': f_bar['time'],
                            'date': entry_time.strftime('%Y-%m-%d'),
                            'dir': 'SHORT',
                            'pnl': (entry - tp) * mult,
                            'win': True
                        })
                        break

    # -------------------------------------------------------------
    # DAILY AGGREGATION & METRICS
    # -------------------------------------------------------------
    def analyze_system(trades, name):
        tdf = pd.DataFrame(trades)
        if len(tdf) == 0:
            print(f"No trades for {name}")
            return
        
        # Total days covered in dataset
        start_date = df['time'].min().date()
        end_date = df['time'].max().date()
        total_trading_days = len(pd.to_datetime(df['time'].dt.date.unique()))

        # Daily group
        daily = tdf.groupby('date').agg(
            trades_count=('pnl', 'count'),
            wins=('win', lambda x: (x == True).sum()),
            losses=('win', lambda x: (x == False).sum()),
            daily_pnl=('pnl', 'sum')
        ).reset_index()

        daily['win_rate'] = (daily['wins'] / daily['trades_count']) * 100
        
        active_days = len(daily)
        trade_frequency_per_day = len(tdf) / total_trading_days
        trade_frequency_active_day = len(tdf) / active_days

        green_days = len(daily[daily['daily_pnl'] > 0])
        red_days = len(daily[daily['daily_pnl'] < 0])
        scratch_days = len(daily[daily['daily_pnl'] == 0])
        daily_win_rate = (green_days / active_days) * 100

        print(f"\n{'='*70}")
        print(f"  SYSTEM: {name}")
        print(f"{'='*70}")
        print(f"Calendar Period Analyzed       : {start_date} to {end_date} ({total_trading_days} trading days)")
        print(f"Total Trades Taken             : {len(tdf)}")
        print(f"Trade Frequency (Overall)      : {trade_frequency_per_day:.2f} trades / calendar trading day")
        print(f"Trade Frequency (When Active)  : {trade_frequency_active_day:.2f} trades / active trading day")
        print(f"Active Trading Days            : {active_days} of {total_trading_days} days (trades fired {active_days/total_trading_days*100:.1f}% of days)")
        print(f"Daily PnL Consistency          : {green_days} Green Days / {red_days} Red Days / {scratch_days} Break-even ({daily_win_rate:.1f}% Winning Days)")
        print(f"Average Daily PnL (Active Days): ${daily['daily_pnl'].mean():.2f}")
        print(f"Best Daily PnL                 : +${daily['daily_pnl'].max():.2f}")
        print(f"Worst Daily PnL                : -${abs(daily['daily_pnl'].min()):.2f}")
        print(f"Overall Trade Win Rate         : {tdf['win'].mean()*100:.1f}% ({tdf['win'].sum()} Wins / {(~tdf['win']).sum()} Losses)")
        print(f"Average Win Size               : +${tdf[tdf['pnl'] > 0]['pnl'].mean():.2f}")
        print(f"Average Loss Size              : -${abs(tdf[tdf['pnl'] < 0]['pnl'].mean()):.2f}")
        print(f"Profit Factor                  : {tdf[tdf['pnl'] > 0]['pnl'].sum() / abs(tdf[tdf['pnl'] < 0]['pnl'].sum()):.2f}")
        print(f"Total Net Profit (0.05 Lot)    : +${tdf['pnl'].sum():.2f}")

        # Show most recent 10 active trading days
        print(f"\n--- Recent 10 Active Days Sample for {name} ---")
        recent = daily.tail(10)
        for _, r in recent.iterrows():
            status = "GREEN" if r['daily_pnl'] > 0 else ("RED" if r['daily_pnl'] < 0 else "FLAT")
            print(f"  {r['date']} | Trades: {r['trades_count']} ({int(r['wins'])}W/{int(r['losses'])}L) | WinRate: {r['win_rate']:5.1f}% | PnL: ${r['daily_pnl']:+8.2f} [{status}]")

    analyze_system(trades_trend, "Trend Pullback Model (EMA50 + RSI)")
    analyze_system(trades_bb, "Bollinger Band Mean Reversion H1")

if __name__ == "__main__":
    run_daily_breakdown()
