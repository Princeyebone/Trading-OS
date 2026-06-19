"""
simulate_loosened_m5.py
Tests "Option 1: Take More Trades" by loosening the M5 Scalping Engine criteria.
Compares the number of signals generated today by the Strict Engine vs Loosened Engine.
"""

import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
import ta

from engine.scalping_engine import ScalpingEngine

class LoosenedScalpingEngine(ScalpingEngine):
    def detect_ema_pullback_scalp(self, current_idx):
        """Loosened version: Allows wider distance from EMA for pullbacks."""
        if current_idx < 10: return None
        
        c = self.m5.iloc[current_idx]
        p = self.m5.iloc[current_idx-1]
        
        # Original strictness: Distance <= 0.3%
        # Loosened strictness: Distance <= 0.8%
        
        if c['close'] > c['ema_50'] and c['ema_20'] > c['ema_50']:
            swing_low = float(self.m5['low'].iloc[current_idx-4:current_idx+1].min())
            dist_to_ema20 = abs(swing_low - c['ema_20']) / c['ema_20'] * 100
            
            if dist_to_ema20 <= 0.8:  # LOOSENED HERE
                # Require bullish rejection
                if c['close'] > c['open']:
                    return {
                        "type": "EMA_PULLBACK_LOOSENED", "direction": "BULLISH",
                        "price": float(c['close']), "entry": float(c['close']),
                        "sl": float(swing_low - 1.0), "tp1": float(c['close'] + 5.0),
                        "rr": 2.0
                    }
                    
        elif c['close'] < c['ema_50'] and c['ema_20'] < c['ema_50']:
            swing_high = float(self.m5['high'].iloc[current_idx-4:current_idx+1].max())
            dist_to_ema20 = abs(swing_high - c['ema_20']) / c['ema_20'] * 100
            
            if dist_to_ema20 <= 0.8: # LOOSENED HERE
                if c['close'] < c['open']:
                    return {
                        "type": "EMA_PULLBACK_LOOSENED", "direction": "BEARISH",
                        "price": float(c['close']), "entry": float(c['close']),
                        "sl": float(swing_high + 1.0), "tp1": float(c['close'] - 5.0),
                        "rr": 2.0
                    }
        return None

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    m5_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start_of_day - timedelta(days=1), now)
    m15_rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M15, start_of_day - timedelta(days=1), now)
    
    m5_df = pd.DataFrame(m5_rates)
    m15_df = pd.DataFrame(m15_rates)
    
    m5_df['time'] = pd.to_datetime(m5_df['time'], unit='s', utc=True)
    m15_df['time'] = pd.to_datetime(m15_df['time'], unit='s', utc=True)
    
    start_idx = m5_df[m5_df['time'] >= start_of_day].index.min()
    
    strict_engine = ScalpingEngine(m5_df, m15_df)
    loosened_engine = LoosenedScalpingEngine(m5_df, m15_df)
    
    strict_signals = 0
    loosened_signals = 0
    
    for i in range(start_idx, len(m5_df) - 1):
        strict_sigs = strict_engine.scan(i)
        if strict_sigs: strict_signals += len(strict_sigs)
        
        loosened_sigs = loosened_engine.scan(i)
        if loosened_sigs: loosened_signals += len(loosened_sigs)

    print(f"Strict Engine Signals Today   : {strict_signals}")
    print(f"Loosened Engine Signals Today : {loosened_signals}")
    if strict_signals > 0:
        print(f"Increase in trading volume    : {((loosened_signals - strict_signals) / strict_signals) * 100:.1f}%")

if __name__ == "__main__":
    run()
