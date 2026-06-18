import sys
from engine import data_fetcher
from engine import indicators
from engine import broker_executor
import logging

logging.basicConfig(level=logging.INFO)

if not broker_executor._init_mt5():
    print("Could not connect to MT5")
    sys.exit(1)

try:
    timeframes, stale = data_fetcher.fetch_all_timeframes()
    if "H4" not in timeframes:
        print("H4 data not found.")
        sys.exit(1)
        
    df_h4 = timeframes["H4"]
    df_h4 = indicators.compute_atr(df_h4)
    
    recent_atrs = df_h4["atr"].dropna().tail(120)
    
    stats = recent_atrs.describe()
    current = recent_atrs.iloc[-1]
    
    print(f"Minimum:         {stats['min']:.2f}")
    print(f"25th Percentile: {stats['25%']:.2f}")
    print(f"Median:          {stats['50%']:.2f}")
    print(f"75th Percentile: {stats['75%']:.2f}")
    print(f"Maximum:         {stats['max']:.2f}")
    print(f"Current:         {current:.2f}")
    
except Exception as e:
    print(f"Error: {e}")
