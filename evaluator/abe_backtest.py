import sys
import os
import pandas as pd
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
from engine import broker_executor
from engine import indicators
from engine import pattern_detector

def fetch_data(symbol="XAUUSD", timeframe=mt5.TIMEFRAME_M15, num_candles=17000):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_candles)
    if rates is None:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

def run_backtest():
    if not broker_executor._init_mt5():
        print("Failed to initialize MT5")
        return
        
    print("Fetching historical data (6 months)...")
    df_m15 = fetch_data(num_candles=18000)
    df_h4 = fetch_data(timeframe=mt5.TIMEFRAME_H4, num_candles=3000)
    
    if df_m15.empty or df_h4.empty:
        print("Failed to fetch data")
        return
        
    print(f"Fetched {len(df_m15)} M15 candles and {len(df_h4)} H4 candles.")
    
    # Compute ATRs
    df_h4 = indicators.compute_atr(df_h4)
    df_m15 = indicators.compute_atr(df_m15)
    
    # Rolling ATR percentile for H4
    atr_percentiles = []
    h4_atrs = df_h4['atr'].values
    for i in range(len(h4_atrs)):
        if i < 120 or pd.isna(h4_atrs[i]):
            atr_percentiles.append(50.0)
            continue
        window = h4_atrs[i-119:i+1]
        current = window[-1]
        pct = (window < current).mean() * 100
        atr_percentiles.append(pct)
        
    df_h4['atr_percentile'] = atr_percentiles
    
    # Align H4 data to M15
    df_h4_aligned = df_h4[['atr', 'atr_percentile']].reindex(df_m15.index, method='ffill')
    df_m15['h4_atr'] = df_h4_aligned['atr']
    df_m15['atr_percentile'] = df_h4_aligned['atr_percentile']
    
    # Backtest params
    TP1_PTS = 8.0   # 80 pips
    SL_PTS = 5.0    # 50 pips
    TP2_PTS = 14.0  # 140 pips
    
    signals = []
    
    highs = df_m15['high'].values
    lows = df_m15['low'].values
    closes = df_m15['close'].values
    opens = df_m15['open'].values
    m15_atrs = df_m15['atr'].values
    atr_pcts = df_m15['atr_percentile'].values
    times = df_m15.index
    
    last_signal_idx = -100
    
    print("Simulating...")
    for i in range(100, len(df_m15) - 100):
        if i - last_signal_idx < 10:
            continue # Cooldown to prevent overlapping signals from same structure
            
        if pd.isna(atr_pcts[i]) or atr_pcts[i] >= 20.0:
            continue
            
        current_m15_atr = m15_atrs[i]
        if pd.isna(current_m15_atr) or current_m15_atr == 0:
            continue
            
        # 1. Compression
        range_10 = max(highs[i-9:i+1]) - min(lows[i-9:i+1])
        is_compression = range_10 < (0.5 * current_m15_atr)
        
        # 2. Repeated Rejections
        rejection_count = 0
        rejection_bands = []
        for j in range(i-9, i+1):
            hl_range = highs[j] - lows[j]
            if hl_range == 0: continue
            
            top_wick = highs[j] - max(opens[j], closes[j])
            bot_wick = min(opens[j], closes[j]) - lows[j]
            
            if top_wick / hl_range > 0.5:
                rejection_bands.append(highs[j])
                rejection_count += 1
            elif bot_wick / hl_range > 0.5:
                rejection_bands.append(lows[j])
                rejection_count += 1
                
        is_rejection = False
        if rejection_count >= 3:
            if (max(rejection_bands) - min(rejection_bands)) / closes[i] < 0.001:
                is_rejection = True
                
        # 3. Liquidity Clustering
        df_slice = df_m15.iloc[i-50:i+1]
        liq_levels = pattern_detector.detect_liquidity_levels(df_slice)
        is_clustering = len(liq_levels) >= 2
        
        if is_compression or is_rejection or is_clustering:
            # Entry model: Straddle the recent 10-candle range
            range_high = max(highs[i-9:i+1])
            range_low = min(lows[i-9:i+1])
            
            direction = "NONE"
            entry_price = 0.0
            trigger_idx = -1
            
            # Step 1: Determine which direction triggers first
            for f in range(i+1, i+101):
                h, l = highs[f], lows[f]
                # Check which side of the range is broken first
                if h >= range_high and l <= range_low:
                    # Both broken in same candle -> Ambiguous (Noise)
                    direction = "AMBIGUOUS"
                    break
                elif h >= range_high:
                    direction = "LONG"
                    entry_price = range_high
                    trigger_idx = f
                    break
                elif l <= range_low:
                    direction = "SHORT"
                    entry_price = range_low
                    trigger_idx = f
                    break
            
            # Step 2: Forward simulate the chosen direction
            tp1_hit, sl_hit, tp2_hit, be_saved = False, False, False, False
            mfe, mae = 0.0, 0.0
            duration = 100
            
            if direction in ["LONG", "SHORT"]:
                for f in range(trigger_idx, i+101):
                    h, l = highs[f], lows[f]
                    
                    if direction == "LONG":
                        if h - entry_price > mfe: mfe = h - entry_price
                        if entry_price - l > mae: mae = entry_price - l
                        
                        if not tp1_hit and not sl_hit:
                            if l <= entry_price - SL_PTS:
                                sl_hit = True
                                duration = f - trigger_idx
                            elif h >= entry_price + TP1_PTS:
                                tp1_hit = True
                                duration = f - trigger_idx
                                
                        if tp1_hit and not tp2_hit:
                            if l <= entry_price:
                                be_saved = True
                                break
                            elif h >= entry_price + TP2_PTS:
                                tp2_hit = True
                                break
                                
                    elif direction == "SHORT":
                        if entry_price - l > mfe: mfe = entry_price - l
                        if h - entry_price > mae: mae = h - entry_price
                        
                        if not tp1_hit and not sl_hit:
                            if h >= entry_price + SL_PTS:
                                sl_hit = True
                                duration = f - trigger_idx
                            elif l <= entry_price - TP1_PTS:
                                tp1_hit = True
                                duration = f - trigger_idx
                                
                        if tp1_hit and not tp2_hit:
                            if h >= entry_price:
                                be_saved = True
                                break
                            elif l <= entry_price - TP2_PTS:
                                tp2_hit = True
                                break
                                
            outcome = "NOISE"
            if tp1_hit: outcome = "WIN"
            elif sl_hit: outcome = "LOSS"
            
            signals.append({
                "time": times[i],
                "compression": is_compression,
                "rejection": is_rejection,
                "clustering": is_clustering,
                "direction": direction,
                "entry_price": entry_price,
                "mfe": mfe,
                "mae": mae,
                "duration": duration,
                "outcome": outcome,
                "be_saved": be_saved,
                "tp2_hit": tp2_hit
            })
            
            last_signal_idx = i

    # Export to CSV
    csv_file = "abe_signals.csv"
    keys = signals[0].keys() if signals else []
    with open(csv_file, 'w', newline='') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(signals)
    print(f"\\nExported raw signals to {csv_file}")

    print(f"\\n--- RESULTS ---")
    print(f"Total LOW_VOL ABE Signals: {len(signals)}")
    if len(signals) > 0:
        wins = sum(1 for s in signals if s["outcome"] == "WIN")
        losses = sum(1 for s in signals if s["outcome"] == "LOSS")
        noise = sum(1 for s in signals if s["outcome"] == "NOISE")
        
        print(f"Win Rate (Hit TP1): {wins/len(signals)*100:.1f}%")
        print(f"Loss Rate (Hit SL): {losses/len(signals)*100:.1f}%")
        print(f"Noise Ratio (No TP/SL or ambiguous): {noise/len(signals)*100:.1f}%")
        
        valid_trades = [s for s in signals if s["direction"] in ["LONG", "SHORT"]]
        if valid_trades:
            avg_mfe = sum(s["mfe"] for s in valid_trades) / len(valid_trades)
            avg_mae = sum(s["mae"] for s in valid_trades) / len(valid_trades)
            print(f"Avg Max Favorable Excursion: {avg_mfe*10:.0f} pips")
            print(f"Avg Max Adverse Excursion: {avg_mae*10:.0f} pips")
            
        be_saves = sum(1 for s in signals if s["be_saved"])
        print(f"BE Saved Rate (Runner hit BE instead of SL): {be_saves/len(signals)*100:.1f}%")
        
        tp2_hits = sum(1 for s in signals if s["tp2_hit"])
        print(f"TP2 Hit Rate: {tp2_hits/len(signals)*100:.1f}%")
        
        durations = [s["duration"] for s in signals if s["outcome"] == "WIN"]
        if durations:
            avg_dur = sum(durations) / len(durations)
            print(f"Avg Time-in-Trade (Winning trades): {avg_dur:.1f} M15 candles ({avg_dur*15/60:.1f} hours)")

if __name__ == "__main__":
    run_backtest()
