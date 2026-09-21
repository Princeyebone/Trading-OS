import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_backtest():
    if not mt5.initialize():
        print("Failed to init MT5")
        return

    # Fetch last 3000 H1 candles (approx 5-6 months of hourly data)
    rates = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_H1, 0, 3000)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print("No rates fetched")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    # Indicators
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()

    # ATR(14)
    df['hl'] = df['high'] - df['low']
    df['hc'] = abs(df['high'] - df['close'].shift(1))
    df['lc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
    df['atr14'] = df['tr'].rolling(14).mean()

    # ADX(14)
    df['up_move'] = df['high'] - df['high'].shift(1)
    df['down_move'] = df['low'].shift(1) - df['low']
    df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
    df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)
    
    alpha = 1.0 / 14.0
    df['tr_smooth'] = df['tr'].ewm(alpha=alpha, adjust=False).mean()
    df['plus_di'] = 100 * (df['plus_dm'].ewm(alpha=alpha, adjust=False).mean() / df['tr_smooth'])
    df['minus_di'] = 100 * (df['minus_dm'].ewm(alpha=alpha, adjust=False).mean() / df['tr_smooth'])
    df['dx'] = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'] + 1e-9))
    df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()

    # Contract spec: 1 lot = 5000 oz. 1 point ($1.00) = $5000. 0.05 lot = $250/pt ($2.50/cent)
    # 0.50 lot (old) = $2500/pt ($25.00/cent)

    def test_strategy(lot_size, use_atr_stops, adx_filter, sl_mult=1.5, tp_mult=2.5):
        trades = []
        pos = None # {direction, entry_price, sl, tp, entry_time}

        for i in range(25, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i-1]
            prev2 = df.iloc[i-2]

            # If position open, check SL/TP against bar high/low
            if pos is not None:
                closed = False
                pnl = 0.0
                exit_price = 0.0
                reason = ""

                if pos['direction'] == 'LONG':
                    if use_atr_stops and row['low'] <= pos['sl']:
                        exit_price = pos['sl']
                        pnl = (exit_price - pos['entry_price']) * 5000 * lot_size
                        reason = "SL"
                        closed = True
                    elif use_atr_stops and row['high'] >= pos['tp']:
                        exit_price = pos['tp']
                        pnl = (exit_price - pos['entry_price']) * 5000 * lot_size
                        reason = "TP"
                        closed = True
                elif pos['direction'] == 'SHORT':
                    if use_atr_stops and row['high'] >= pos['sl']:
                        exit_price = pos['sl']
                        pnl = (pos['entry_price'] - exit_price) * 5000 * lot_size
                        reason = "SL"
                        closed = True
                    elif use_atr_stops and row['low'] <= pos['tp']:
                        exit_price = pos['tp']
                        pnl = (pos['entry_price'] - exit_price) * 5000 * lot_size
                        reason = "TP"
                        closed = True

                if closed:
                    trades.append({
                        'dir': pos['direction'],
                        'entry_time': pos['entry_time'],
                        'exit_time': row['time'],
                        'entry': pos['entry_price'],
                        'exit': exit_price,
                        'pnl': pnl,
                        'reason': reason
                    })
                    pos = None

            # Crossover signal on closed candles (prev2 to prev)
            bullish_cross = (prev2['ema9'] <= prev2['ema21']) and (prev['ema9'] > prev['ema21'])
            bearish_cross = (prev2['ema9'] >= prev2['ema21']) and (prev['ema9'] < prev['ema21'])

            atr = prev['atr14']
            adx = prev['adx']

            # Long entry
            if bullish_cross:
                if (not adx_filter) or (adx >= 20.0):
                    # If we had a position (e.g. reverse), close it
                    if pos is not None:
                        if pos['direction'] == 'SHORT':
                            exit_price = row['open']
                            pnl = (pos['entry_price'] - exit_price) * 5000 * lot_size
                            trades.append({
                                'dir': pos['direction'],
                                'entry_time': pos['entry_time'],
                                'exit_time': row['time'],
                                'entry': pos['entry_price'],
                                'exit': exit_price,
                                'pnl': pnl,
                                'reason': "REVERSE"
                            })
                            pos = None
                    if pos is None:
                        entry = row['open']
                        pos = {
                            'direction': 'LONG',
                            'entry_price': entry,
                            'sl': entry - (sl_mult * atr) if use_atr_stops else 0.0,
                            'tp': entry + (tp_mult * atr) if use_atr_stops else 0.0,
                            'entry_time': row['time']
                        }

            # Short entry
            elif bearish_cross:
                if (not adx_filter) or (adx >= 20.0):
                    if pos is not None:
                        if pos['direction'] == 'LONG':
                            exit_price = row['open']
                            pnl = (exit_price - pos['entry_price']) * 5000 * lot_size
                            trades.append({
                                'dir': pos['direction'],
                                'entry_time': pos['entry_time'],
                                'exit_time': row['time'],
                                'entry': pos['entry_price'],
                                'exit': exit_price,
                                'pnl': pnl,
                                'reason': "REVERSE"
                            })
                            pos = None
                    if pos is None:
                        entry = row['open']
                        pos = {
                            'direction': 'SHORT',
                            'entry_price': entry,
                            'sl': entry + (sl_mult * atr) if use_atr_stops else 0.0,
                            'tp': entry - (tp_mult * atr) if use_atr_stops else 0.0,
                            'entry_time': row['time']
                        }

        # Calculate metrics
        if not trades:
            return {"trades": 0, "net_pnl": 0, "wr": 0, "max_dd": 0, "profit_factor": 0}
        
        tdf = pd.DataFrame(trades)
        wins = tdf[tdf['pnl'] > 0]
        losses = tdf[tdf['pnl'] <= 0]
        win_rate = len(wins) / len(tdf) * 100
        net_pnl = tdf['pnl'].sum()
        gross_profit = wins['pnl'].sum()
        gross_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
        profit_factor = gross_profit / (gross_loss if gross_loss > 0 else 1.0)
        
        # Drawdown
        tdf['cum_pnl'] = tdf['pnl'].cumsum()
        tdf['peak'] = tdf['cum_pnl'].cummax()
        tdf['dd'] = tdf['peak'] - tdf['cum_pnl']
        max_dd = tdf['dd'].max()

        return {
            "trades": len(tdf),
            "net_pnl": round(net_pnl, 2),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "max_dd": round(max_dd, 2),
            "tp_exits": len(tdf[tdf['reason'] == 'TP']),
            "sl_exits": len(tdf[tdf['reason'] == 'SL']),
            "rev_exits": len(tdf[tdf['reason'] == 'REVERSE']),
        }

    print("=== BACKTESTING SILVER (XAGUSD) H1 OVER 3000 CANDLES (~5 MONTHS) ===")
    
    # 1. Old Flawed Baseline (0.50 Lot, No SL, No TP, No Filter)
    old_res = test_strategy(lot_size=0.50, use_atr_stops=False, adx_filter=False)
    print(f"\n[1] OLD SYSTEM (0.50 Lot, Pure SAR, No SL/TP):")
    print(f"    Trades: {old_res['trades']}, Net PnL: ${old_res['net_pnl']:,.2f}, Win Rate: {old_res['win_rate']}%, PF: {old_res['profit_factor']}, Max DD: ${old_res['max_dd']:,.2f}")

    # 2. Normalized Sizing Only (0.05 Lot, No SL/TP)
    norm_res = test_strategy(lot_size=0.05, use_atr_stops=False, adx_filter=False)
    print(f"\n[2] NORMALIZED LOT (0.05 Lot, Pure SAR, No SL/TP):")
    print(f"    Trades: {norm_res['trades']}, Net PnL: ${norm_res['net_pnl']:,.2f}, Win Rate: {norm_res['win_rate']}%, PF: {norm_res['profit_factor']}, Max DD: ${norm_res['max_dd']:,.2f}")

    # 3. Proposed Solution (0.05 Lot, 1.5 ATR SL, 2.5 ATR TP, ADX Filter)
    prop_res = test_strategy(lot_size=0.05, use_atr_stops=True, adx_filter=True, sl_mult=1.5, tp_mult=2.5)
    print(f"\n[3] PROPOSED SYSTEM (0.05 Lot, 1.5 ATR SL, 2.5 ATR TP, ADX >= 20):")
    print(f"    Trades: {prop_res['trades']}, Net PnL: ${prop_res['net_pnl']:,.2f}, Win Rate: {prop_res['win_rate']}%, PF: {prop_res['profit_factor']}, Max DD: ${prop_res['max_dd']:,.2f}")
    print(f"    Exits breakdown -> TP: {prop_res['tp_exits']}, SL: {prop_res['sl_exits']}, Reverse: {prop_res['rev_exits']}")

    # 4. Variation: 1.5 ATR SL / 3.0 ATR TP with ADX >= 22
    prop_res2 = test_strategy(lot_size=0.05, use_atr_stops=True, adx_filter=True, sl_mult=1.5, tp_mult=3.0)
    print(f"\n[4] RUNNER VARIATION (0.05 Lot, 1.5 ATR SL, 3.0 ATR TP, ADX >= 20):")
    print(f"    Trades: {prop_res2['trades']}, Net PnL: ${prop_res2['net_pnl']:,.2f}, Win Rate: {prop_res2['win_rate']}%, PF: {prop_res2['profit_factor']}, Max DD: ${prop_res2['max_dd']:,.2f}")
    print(f"    Exits breakdown -> TP: {prop_res2['tp_exits']}, SL: {prop_res2['sl_exits']}, Reverse: {prop_res2['rev_exits']}")

if __name__ == "__main__":
    run_silver_backtest()
