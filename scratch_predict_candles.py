import sys
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

def analyze_timeframe(tf_name, tf_const, num_candles=50000):
    rates = mt5.copy_rates_from_pos("XAUUSD", tf_const, 0, num_candles)
    if rates is None:
        print(f"No rates retrieved for {tf_name}")
        return
        
    df = pd.DataFrame(rates)
    
    total_bull_predictions = 0
    correct_bull_predictions = 0
    
    total_bear_predictions = 0
    correct_bear_predictions = 0
    
    for i in range(1, len(df)):
        c1 = df.iloc[i-1]
        c2 = df.iloc[i]
        
        c1_bullish = c1['close'] > c1['open']
        c1_bearish = c1['close'] < c1['open']
        
        c2_bullish = c2['close'] > c2['open']
        c2_bearish = c2['close'] < c2['open']
        
        # PREDICTION 1: Candle opens "on top of a buy candle" -> Predict it will be a buy candle
        # We define "on top of" as C2 opening at or above the previous close.
        if c1_bullish and c2['open'] >= c1['close']:
            total_bull_predictions += 1
            if c2_bullish:
                correct_bull_predictions += 1
                
        # PREDICTION 2: Candle opens "below a sell candle" -> Predict it will be a sell candle
        # We define "below" as C2 opening at or below the previous close.
        if c1_bearish and c2['open'] <= c1['close']:
            total_bear_predictions += 1
            if c2_bearish:
                correct_bear_predictions += 1
                
    bull_acc = (correct_bull_predictions / total_bull_predictions) * 100 if total_bull_predictions > 0 else 0
    bear_acc = (correct_bear_predictions / total_bear_predictions) * 100 if total_bear_predictions > 0 else 0
    
    total_preds = total_bull_predictions + total_bear_predictions
    total_correct = correct_bull_predictions + correct_bear_predictions
    overall_acc = (total_correct / total_preds) * 100 if total_preds > 0 else 0
    
    print(f"--- TIMEFRAME: {tf_name} ({len(df)} candles tested) ---")
    print(f"BULLISH Predictions: {correct_bull_predictions}/{total_bull_predictions} ({bull_acc:.1f}%)")
    print(f"BEARISH Predictions: {correct_bear_predictions}/{total_bear_predictions} ({bear_acc:.1f}%)")
    print(f"OVERALL Accuracy: {total_correct}/{total_preds} ({overall_acc:.1f}%)\n")

print("Running Prediction Analysis on Gold (XAUUSD)...\n")
analyze_timeframe("M5 (5 Minute)", mt5.TIMEFRAME_M5, 50000)
analyze_timeframe("M15 (15 Minute)", mt5.TIMEFRAME_M15, 50000)
analyze_timeframe("H1 (1 Hour)", mt5.TIMEFRAME_H1, 10000)
analyze_timeframe("D1 (Daily)", mt5.TIMEFRAME_D1, 5000)

mt5.shutdown()
