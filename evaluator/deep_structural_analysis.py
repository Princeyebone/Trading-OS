"""
evaluator/deep_structural_analysis.py
Performs deep structural analysis of WIN vs LOSS trades from abe_signals.csv.
"""
import os
import sys
import pandas as pd
from datetime import datetime, timezone
import numpy as np

# Ensure backend path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.adapters.mt5_fetcher import MT5Fetcher

def analyze_signals():
    csv_path = os.path.join(os.path.dirname(__file__), "..", "abe_signals.csv")
    if not os.path.exists(csv_path):
        print("abe_signals.csv not found")
        return

    df = pd.read_csv(csv_path)
    
    # Filter to pure WIN/LOSS
    df = df[df["outcome"].isin(["WIN", "LOSS"])]
    if df.empty:
        print("No WIN/LOSS trades found")
        return
        
    print(f"Loaded {len(df)} resolved trades ({len(df[df['outcome']=='WIN'])} WIN, {len(df[df['outcome']=='LOSS'])} LOSS)")

    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 initialize failed")
        return
        
    symbol = "XAUUSD"
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 18000)
    mt5.shutdown()
    
    if rates is None or len(rates) == 0:
        print("Failed to fetch MT5 data")
        return
        
    mt5_data = pd.DataFrame(rates)
    mt5_data['time'] = pd.to_datetime(mt5_data['time'], unit='s')
    mt5_data.set_index('time', inplace=True)

    mt5_data.index = mt5_data.index.tz_convert('UTC') if mt5_data.index.tz is not None else mt5_data.index.tz_localize('UTC')

    metrics = []

    for _, row in df.iterrows():
        # Parse time
        try:
            sig_time = pd.to_datetime(row['time']).tz_localize('UTC')
        except:
            try:
                sig_time = pd.to_datetime(row['time']).tz_convert('UTC')
            except:
                continue

        # Get historical slice: 20 candles before, up to 10 candles after
        loc = mt5_data.index.get_indexer([sig_time], method='bfill')[0]
        if loc < 20 or loc >= len(mt5_data) - 10:
            continue
            
        pre_candles = mt5_data.iloc[loc-20:loc]
        signal_candle = mt5_data.iloc[loc]
        post_candles = mt5_data.iloc[loc:loc+40] # up to 40 for MFE

        # 1. Compression Quality (Range of last 10 candles / ATR)
        recent_10 = mt5_data.iloc[loc-10:loc]
        range_10 = recent_10['high'].max() - recent_10['low'].min()
        
        # Calculate ATR(14) at signal time
        tr = np.maximum(
            mt5_data.iloc[loc-14:loc]['high'] - mt5_data.iloc[loc-14:loc]['low'],
            np.maximum(
                abs(mt5_data.iloc[loc-14:loc]['high'] - mt5_data.iloc[loc-15:loc-1]['close'].values),
                abs(mt5_data.iloc[loc-14:loc]['low'] - mt5_data.iloc[loc-15:loc-1]['close'].values)
            )
        )
        atr_14 = tr.mean()
        
        compression_ratio = range_10 / atr_14 if atr_14 > 0 else 0

        # 2. Liquidity Structure (Single vs Bilateral)
        # Find local peaks/troughs in the 20 pre-candles
        highs = pre_candles['high'].values
        lows = pre_candles['low'].values
        
        # Simple cluster detection: if multiple highs within 0.1 * atr of max high
        max_h = highs.max()
        min_l = lows.min()
        
        high_cluster = np.sum(highs >= max_h - (0.1 * atr_14)) >= 2
        low_cluster = np.sum(lows <= min_l + (0.1 * atr_14)) >= 2
        
        if high_cluster and low_cluster:
            liq_struct = "BILATERAL"
        elif high_cluster:
            liq_struct = "HIGH_ONLY"
        elif low_cluster:
            liq_struct = "LOW_ONLY"
        else:
            liq_struct = "NONE"

        # 3. Pre-breakout Sweep
        # Did any of the last 3 candles wick outside the cluster boundaries and close inside?
        last_3 = pre_candles.iloc[-3:]
        sweep = False
        for _, c in last_3.iterrows():
            if c['high'] > max_h and c['close'] <= max_h:
                sweep = True
            if c['low'] < min_l and c['close'] >= min_l:
                sweep = True

        # 4. Time to Expansion (MFE offset)
        entry = row['entry_price']
        direction = row['direction']
        mfe_candle_offset = -1
        max_dist = -1
        
        for i, (_, c) in enumerate(post_candles.iterrows()):
            dist = (c['high'] - entry) if direction == 'LONG' else (entry - c['low'])
            if dist > max_dist:
                max_dist = dist
                mfe_candle_offset = i

        metrics.append({
            "outcome": row['outcome'],
            "compression_ratio": compression_ratio,
            "liq_struct": liq_struct,
            "sweep": sweep,
            "mfe_offset": mfe_candle_offset
        })

    m_df = pd.DataFrame(metrics)
    
    if m_df.empty:
        print("No valid metrics computed")
        return

    wins = m_df[m_df['outcome'] == 'WIN']
    losses = m_df[m_df['outcome'] == 'LOSS']

    print("\n" + "="*50)
    print("WINNER VS LOSER STRUCTURAL ANALYSIS")
    print("="*50)
    
    print(f"\nTotal Trades Analysed: {len(m_df)} ({len(wins)} WIN, {len(losses)} LOSS)")
    
    # LIQUIDITY STRUCTURE
    print("\n--- Liquidity Structure ---")
    print("WINNERS:")
    print(wins['liq_struct'].value_counts(normalize=True).map('{:.1%}'.format))
    print("\nLOSERS:")
    print(losses['liq_struct'].value_counts(normalize=True).map('{:.1%}'.format))
    
    # COMPRESSION
    print("\n--- Compression Quality (Range_10 / ATR_14) ---")
    print(f"WINNERS Avg: {wins['compression_ratio'].mean():.2f} (lower is tighter)")
    print(f"LOSERS Avg:  {losses['compression_ratio'].mean():.2f}")
    
    # PRE-BREAKOUT SWEEP
    print("\n--- Pre-Breakout Sweep (Last 3 candles) ---")
    print(f"WINNERS with sweep: {wins['sweep'].mean():.1%}")
    print(f"LOSERS with sweep:  {losses['sweep'].mean():.1%}")
    
    # TIME TO EXPANSION
    print("\n--- Time to Peak Expansion (Candles to MFE) ---")
    print(f"WINNERS Avg: {wins['mfe_offset'].mean():.1f} candles")
    print(f"LOSERS Avg:  {losses['mfe_offset'].mean():.1f} candles")

if __name__ == "__main__":
    analyze_signals()
