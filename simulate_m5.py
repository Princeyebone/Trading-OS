import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta

def run_simulation():
    if not mt5.initialize():
        print("MT5 initialization failed")
        return

    symbol = "XAUUSD"
    timeframe = mt5.TIMEFRAME_M5
    
    # Fetch 60 days of M5 data
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 15000)
    if rates is None or len(rates) == 0:
        print("Failed to fetch rates")
        return
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    total_trades = 0
    wins = 0
    losses = 0
    total_pips = 0.0
    
    # We will iterate through the dataframe.
    # At index i, we evaluate the pattern formed by i-2 and i-1.
    for i in range(2, len(df)):
        c1 = df.iloc[i-2]
        c2 = df.iloc[i-1]
        
        is_c1_bearish = c1['close'] < c1['open']
        is_c2_bullish = c2['close'] > c2['open']
        
        is_c1_bullish = c1['close'] > c1['open']
        is_c2_bearish = c2['close'] < c2['open']
        
        c2_range = c2['high'] - c2['low']
        
        direction = None
        limit_price = 0.0
        sl_price = 0.0
        
        # Bullish Shift
        if is_c1_bearish and is_c2_bullish and c2['close'] > c1['high'] and c2_range >= 1.5:
            direction = "LONG"
            limit_price = c2['low'] + (c2_range * 0.5)
            sl_price = c2['low'] - 0.5
            
        # Bearish Shift
        elif is_c1_bullish and is_c2_bearish and c2['close'] < c1['low'] and c2_range >= 1.5:
            direction = "SHORT"
            limit_price = c2['high'] - (c2_range * 0.5)
            sl_price = c2['high'] + 0.5
            
        if direction:
            # We have a setup. Now we look forward from index i to see if it triggers, and then how it plays out.
            triggered = False
            active = False
            
            highest_profit_pips = 0.0
            locked_pips = 0.0
            current_sl = sl_price
            
            for j in range(i, len(df)):
                future_c = df.iloc[j]
                
                if not active:
                    # Check if limit order gets triggered
                    if direction == "LONG":
                        if future_c['low'] <= limit_price:
                            active = True
                            # It triggered. But did it immediately hit SL on the same candle?
                            if future_c['low'] <= current_sl:
                                total_trades += 1
                                losses += 1
                                loss_pips = (current_sl - limit_price) * 10
                                total_pips += loss_pips
                                break
                    elif direction == "SHORT":
                        if future_c['high'] >= limit_price:
                            active = True
                            if future_c['high'] >= current_sl:
                                total_trades += 1
                                losses += 1
                                loss_pips = (limit_price - current_sl) * 10
                                total_pips += loss_pips
                                break
                
                else: # ACTIVE TRADE
                    if direction == "LONG":
                        # Simulate the candle's move. We take the high first to see if it ratchets trailing stop
                        profit_pips = (future_c['high'] - limit_price) * 10
                        if profit_pips > highest_profit_pips:
                            highest_profit_pips = profit_pips
                            
                        if highest_profit_pips >= 20.0:
                            new_locked = highest_profit_pips - 20.0
                            if new_locked > locked_pips:
                                locked_pips = new_locked
                                current_sl = limit_price + (locked_pips / 10.0)
                                
                        # Now check if the low hit the SL
                        if future_c['low'] <= current_sl:
                            total_trades += 1
                            final_pips = (current_sl - limit_price) * 10
                            total_pips += final_pips
                            if final_pips > 0:
                                wins += 1
                            else:
                                losses += 1
                            break
                            
                    elif direction == "SHORT":
                        profit_pips = (limit_price - future_c['low']) * 10
                        if profit_pips > highest_profit_pips:
                            highest_profit_pips = profit_pips
                            
                        if highest_profit_pips >= 20.0:
                            new_locked = highest_profit_pips - 20.0
                            if new_locked > locked_pips:
                                locked_pips = new_locked
                                current_sl = limit_price - (locked_pips / 10.0)
                                
                        if future_c['high'] >= current_sl:
                            total_trades += 1
                            final_pips = (limit_price - current_sl) * 10
                            total_pips += final_pips
                            if final_pips > 0:
                                wins += 1
                            else:
                                losses += 1
                            break

    print(f"--- M5 2-Candle Engulfing (50% Retracement & 20-pip Trail) Backtest ---")
    print(f"Total Setups Triggered: {total_trades}")
    print(f"Wins (Locked Profit): {wins}")
    print(f"Losses (Hit initial SL or 0 lock): {losses}")
    if total_trades > 0:
        print(f"Win Rate: {(wins/total_trades)*100:.2f}%")
        print(f"Total Pips Gained/Lost: {total_pips:.1f}")
        print(f"Average Pips Per Trade: {total_pips/total_trades:.1f}")

run_simulation()
