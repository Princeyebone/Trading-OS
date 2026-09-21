import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def examine_problem_days():
    if not mt5.initialize():
        return
    rates_m1 = mt5.copy_rates_from_pos("XAGUSD", mt5.TIMEFRAME_M1, 0, 20000)
    mt5.shutdown()

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    
    # Check Sept 8 and Sept 15
    for d in [pd.to_datetime('2026-09-08').date(), pd.to_datetime('2026-09-15').date()]:
        sub = df[df['date'] == d]
        high = sub['high'].max()
        low = sub['low'].min()
        start = sub['open'].iloc[0]
        end = sub['close'].iloc[-1]
        print(f"Date: {d} | Open: {start:.3f}, Close: {end:.3f}, Range: {low:.3f} to {high:.3f} (Move: {end-start:+.3f}, Range: {high-low:.3f})")

if __name__ == "__main__":
    examine_problem_days()
