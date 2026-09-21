import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timezone, timedelta

def backtest_all_days_gold():
    if not mt5.initialize():
        return

    # Fetch 20,000 M1 bars for XAUUSD
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 20000)
    mt5.shutdown()

    if rates is None or len(rates) < 100:
        return

    df = pd.DataFrame(rates)
    df['time_dt'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df['date'] = df['time_dt'].dt.date
    
    # Indicators matching XAU-i6 exactly
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2.2)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    df['bb_mid'] = bb.bollinger_mavg()
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)

    # Let's run day by day
    dates = sorted(df['date'].unique())
    print(f"Total Unique Days in dataset: {len(dates)}")

    # Test lock targets & adaptive recovery lot
    # In original: LOT_SIZE = 0.05, MIN_TARGET_POINTS = 1.20, MAX_TARGET = 4.0, MAX_SL = 3.50
    # Let's test with Session Lock (e.g. +$25.00 or +$30.00 lock):
    for lock_target in [20.0, 25.0, 30.0, None]:
        daily_records = {}
        for d in dates:
            sub = df[df['date'] == d]
            if len(sub) < 50:
                continue

            day_pnl = 0.0
            trades = []
            in_trade = False
            trade_dir = None
            entry_price = 0.0
            sl_price = 0.0
            tp_price = 0.0
            cur_lot = 0.05
            consec_losses = 0
            locked = False

            MIN_TARGET_POINTS = 1.20
            MAX_TARGET_POINTS = 4.00
            MAX_SL_POINTS = 3.50

            for i in range(sub.index[0], sub.index[-1] + 1):
                c = df.iloc[i]

                if locked:
                    break

                if in_trade:
                    hit_tp = False
                    hit_sl = False

                    if trade_dir == "LONG":
                        if c['low'] <= sl_price:
                            hit_sl = True
                        elif c['high'] >= tp_price:
                            hit_tp = True
                    else:
                        if c['high'] >= sl_price:
                            hit_sl = True
                        elif c['low'] <= tp_price:
                            hit_tp = True

                    if hit_tp or hit_sl:
                        in_trade = False
                        if hit_tp:
                            pnl = abs(tp_price - entry_price) * 100 * cur_lot
                            consec_losses = 0
                        else:
                            pnl = -abs(entry_price - sl_price) * 100 * cur_lot
                            consec_losses += 1

                        day_pnl += pnl
                        trades.append({'pnl': pnl, 'win': pnl > 0})

                        if lock_target is not None and day_pnl >= lock_target:
                            locked = True
                            break
                        continue

                # Signal evaluation
                if i < 25: continue
                prev = df.iloc[i-1]
                current_price = float(prev['close'])
                bb_upper = float(prev['bb_upper'])
                bb_lower = float(prev['bb_lower'])
                bb_mid = float(prev['bb_mid'])
                rsi = float(prev['rsi'])

                direction = None
                if current_price < bb_lower and rsi < 35.0:
                    direction = "LONG"
                elif current_price > bb_upper and rsi > 65.0:
                    direction = "SHORT"

                if direction:
                    target_points = abs(current_price - bb_mid)
                    target_points = max(MIN_TARGET_POINTS, min(MAX_TARGET_POINTS, target_points))
                    sl_dist = min(MAX_SL_POINTS, max(1.80, target_points * 1.2))

                    in_trade = True
                    trade_dir = direction
                    entry_price = float(df.iloc[i]['open'])
                    sl_price = round(entry_price - sl_dist, 2) if direction == "LONG" else round(entry_price + sl_dist, 2)
                    tp_price = round(entry_price + target_points, 2) if direction == "LONG" else round(entry_price - target_points, 2)

                    # Dynamic lot size if in deficit
                    if consec_losses == 0:
                        cur_lot = 0.08 if day_pnl < 0 else 0.05
                    elif consec_losses == 1:
                        cur_lot = 0.08
                    elif consec_losses == 2:
                        cur_lot = 0.14
                    else:
                        cur_lot = 0.22

            if len(trades) > 0:
                daily_records[d] = {
                    'pnl': day_pnl,
                    'trades': len(trades),
                    'wins': sum(1 for t in trades if t['win']),
                    'losses': sum(1 for t in trades if not t['win'])
                }

        green_days = sum(1 for r in daily_records.values() if r['pnl'] > 0)
        tot = len(daily_records)
        tot_pnl = sum(r['pnl'] for r in daily_records.values())
        print(f"Lock Target: {lock_target} -> {green_days}/{tot} GREEN ({green_days/tot*100:.1f}%) | Net: ${tot_pnl:+.2f}")
        for d, r in sorted(daily_records.items()):
            status = "[GREEN]" if r['pnl'] > 0 else "[RED]"
            print(f"  {d} | {r['trades']:2d} trades ({r['wins']}W / {r['losses']}L) | PnL: ${r['pnl']:+8.2f} {status}")
        print("=" * 70)

if __name__ == "__main__":
    backtest_all_days_gold()
