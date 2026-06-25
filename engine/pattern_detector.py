"""
engine/pattern_detector.py — Detect SMC patterns on XAU/USD candles.

Patterns detected:
  - Order Blocks (OB): Last up/down candle before a strong move
  - Fair Value Gaps (FVG): Imbalance between 3 consecutive candles
  - Break of Structure (BOS): Higher high / Lower low on trend changes
  - Liquidity Levels: Equal highs / Equal lows (potential sweep targets)
"""
import logging
from typing import List, Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)

# Tolerances
FVG_MIN_GAP_RATIO = 0.0003    # FVG must be > 0.03% of price to be significant
OB_LOOKBACK = 20              # bars to scan for order blocks
LIQUIDITY_TOLERANCE = 0.001   # 0.1% — how close must highs/lows be to be "equal"
BOS_LOOKBACK = 30             # bars to scan for structure breaks


def detect_order_blocks(df: pd.DataFrame, direction: str = "both") -> List[Dict]:
    """
    Detect bullish and bearish order blocks.
    Bullish OB: last bearish candle before a strong bullish move.
    Bearish OB: last bullish candle before a strong bearish move.
    """
    blocks = []
    n = len(df)
    if n < OB_LOOKBACK + 3:
        return blocks

    closes = df["close"].values
    opens  = df["open"].values
    highs  = df["high"].values
    lows   = df["low"].values

    for i in range(2, min(n - 1, OB_LOOKBACK)):
        idx = n - 1 - i  # scan from most recent backward

        # Bullish OB: bearish candle (close < open) followed by strong bullish move
        if opens[idx] > closes[idx]:  # bearish candle
            # Check if the next 2 candles are strongly bullish
            move = closes[idx + 2] - closes[idx]
            candle_range = opens[idx] - closes[idx]
            if move > candle_range * 2 and move > 0:
                if direction in ("both", "long"):
                    blocks.append({
                        "type": "ORDER_BLOCK",
                        "direction": "BULLISH",
                        "high": float(highs[idx]),
                        "low": float(lows[idx]),
                        "mid": float((highs[idx] + lows[idx]) / 2),
                        "bar_index": int(idx),
                        "timestamp": str(df.index[idx]),
                        "confidence": 75,
                    })

        # Bearish OB: bullish candle followed by strong bearish move
        elif closes[idx] > opens[idx]:  # bullish candle
            move = closes[idx] - closes[idx + 2]
            candle_range = closes[idx] - opens[idx]
            if move > candle_range * 2 and move > 0:
                if direction in ("both", "short"):
                    blocks.append({
                        "type": "ORDER_BLOCK",
                        "direction": "BEARISH",
                        "high": float(highs[idx]),
                        "low": float(lows[idx]),
                        "mid": float((highs[idx] + lows[idx]) / 2),
                        "bar_index": int(idx),
                        "timestamp": str(df.index[idx]),
                        "confidence": 75,
                    })

    return blocks[:5]  # return top 5 most recent

def detect_fvg_order_blocks(df: pd.DataFrame, direction: str = "both") -> List[Dict]:
    """
    Detect True SMC Order Blocks.
    A valid OB must be followed by an impulse candle, and the subsequent 
    confirming candle must leave a Fair Value Gap (FVG) of >= 0.5 points (5 pips).
    """
    blocks = []
    n = len(df)
    if n < OB_LOOKBACK + 3:
        return blocks

    closes = df["close"].values
    opens  = df["open"].values
    highs  = df["high"].values
    lows   = df["low"].values

    for i in range(2, min(n - 1, OB_LOOKBACK)):
        idx = n - 1 - i  # scan from most recent backward
        
        c_confirm_idx = idx + 2
        c_impulse_idx = idx + 1
        c_ob_idx = idx
        
        if c_confirm_idx >= n:
            continue

        # Bullish FVG OB
        # OB is bearish, impulse is bullish & engulfing
        if opens[c_ob_idx] > closes[c_ob_idx] and closes[c_impulse_idx] > opens[c_impulse_idx] and closes[c_impulse_idx] > highs[c_ob_idx]:
            # FVG Check: c_confirm's LOW must be higher than c_ob's HIGH
            gap_size = lows[c_confirm_idx] - highs[c_ob_idx]
            if gap_size >= 0.5: # 5 pips
                if direction in ("both", "long"):
                    blocks.append({
                        "type": "ORDER_BLOCK",
                        "direction": "BULLISH",
                        "high": float(highs[c_ob_idx]),
                        "low": float(lows[c_ob_idx]),
                        "mid": float((highs[c_ob_idx] + lows[c_ob_idx]) / 2),
                        "bar_index": int(c_ob_idx),
                        "timestamp": str(df.index[c_ob_idx]),
                        "confidence": 95,
                    })
                    
        # Bearish FVG OB
        # OB is bullish, impulse is bearish & engulfing
        elif closes[c_ob_idx] > opens[c_ob_idx] and closes[c_impulse_idx] < opens[c_impulse_idx] and closes[c_impulse_idx] < lows[c_ob_idx]:
            # FVG Check: c_confirm's HIGH must be lower than c_ob's LOW
            gap_size = lows[c_ob_idx] - highs[c_confirm_idx]
            if gap_size >= 0.5:
                if direction in ("both", "short"):
                    blocks.append({
                        "type": "ORDER_BLOCK",
                        "direction": "BEARISH",
                        "high": float(highs[c_ob_idx]),
                        "low": float(lows[c_ob_idx]),
                        "mid": float((highs[c_ob_idx] + lows[c_ob_idx]) / 2),
                        "bar_index": int(c_ob_idx),
                        "timestamp": str(df.index[c_ob_idx]),
                        "confidence": 95,
                    })

    return blocks[:5]


def detect_fair_value_gaps(df: pd.DataFrame) -> List[Dict]:
    """
    Detect Fair Value Gaps (FVGs / imbalances).
    Bullish FVG: candle[i-1].high < candle[i+1].low
    Bearish FVG: candle[i-1].low > candle[i+1].high
    """
    fvgs = []
    highs = df["high"].values
    lows  = df["low"].values
    closes = df["close"].values
    n = len(df)

    for i in range(1, n - 1):
        # Bullish FVG
        gap_up = lows[i + 1] - highs[i - 1]
        if gap_up > 0:
            gap_ratio = gap_up / closes[i]
            if gap_ratio > FVG_MIN_GAP_RATIO:
                fvgs.append({
                    "type": "FAIR_VALUE_GAP",
                    "direction": "BULLISH",
                    "high": float(lows[i + 1]),
                    "low": float(highs[i - 1]),
                    "mid": float((lows[i + 1] + highs[i - 1]) / 2),
                    "gap_size": round(float(gap_up), 2),
                    "bar_index": int(i),
                    "timestamp": str(df.index[i]),
                    "confidence": 70,
                })

        # Bearish FVG
        gap_down = lows[i - 1] - highs[i + 1]
        if gap_down > 0:
            gap_ratio = gap_down / closes[i]
            if gap_ratio > FVG_MIN_GAP_RATIO:
                fvgs.append({
                    "type": "FAIR_VALUE_GAP",
                    "direction": "BEARISH",
                    "high": float(lows[i - 1]),
                    "low": float(highs[i + 1]),
                    "mid": float((lows[i - 1] + highs[i + 1]) / 2),
                    "gap_size": round(float(gap_down), 2),
                    "bar_index": int(i),
                    "timestamp": str(df.index[i]),
                    "confidence": 70,
                })

    # Return 5 most recent FVGs
    return sorted(fvgs, key=lambda x: x["bar_index"], reverse=True)[:5]


def detect_break_of_structure(df: pd.DataFrame) -> List[Dict]:
    """
    Detect Break of Structure (BOS).
    Bullish BOS: price breaks above the last significant swing high.
    Bearish BOS: price breaks below the last significant swing low.
    """
    bos_events = []
    if len(df) < BOS_LOOKBACK:
        return bos_events

    recent = df.tail(BOS_LOOKBACK)
    highs = recent["high"].values
    lows  = recent["low"].values
    closes = recent["close"].values
    n = len(highs)

    # Find swing highs/lows
    swing_highs = []
    swing_lows  = []
    for i in range(2, n - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append((i, highs[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append((i, lows[i]))

    current_close = closes[-1]

    # Bullish BOS: close breaks above last swing high
    if swing_highs:
        last_swing_high_idx, last_swing_high = swing_highs[-1]
        if current_close > last_swing_high:
            bos_events.append({
                "type": "BREAK_OF_STRUCTURE",
                "direction": "BULLISH",
                "level": float(last_swing_high),
                "bar_index": int(last_swing_high_idx),
                "timestamp": str(recent.index[last_swing_high_idx]),
                "confidence": 80,
            })

    # Bearish BOS: close breaks below last swing low
    if swing_lows:
        last_swing_low_idx, last_swing_low = swing_lows[-1]
        if current_close < last_swing_low:
            bos_events.append({
                "type": "BREAK_OF_STRUCTURE",
                "direction": "BEARISH",
                "level": float(last_swing_low),
                "bar_index": int(last_swing_low_idx),
                "timestamp": str(recent.index[last_swing_low_idx]),
                "confidence": 80,
            })

    return bos_events


def detect_liquidity_levels(df: pd.DataFrame) -> List[Dict]:
    """
    Detect liquidity levels — clusters of equal highs or equal lows.
    These are sweep targets and stop-hunt zones.
    """
    levels = []
    if len(df) < 20:
        return levels

    recent = df.tail(50)
    highs = recent["high"].values
    lows  = recent["low"].values
    close = recent["close"].iloc[-1]

    # Find equal highs (within tolerance)
    for i in range(len(highs)):
        for j in range(i + 3, len(highs)):  # at least 3 bars apart
            if abs(highs[i] - highs[j]) / close < LIQUIDITY_TOLERANCE:
                level = (highs[i] + highs[j]) / 2
                levels.append({
                    "type": "LIQUIDITY",
                    "subtype": "EQUAL_HIGHS",
                    "level": float(level),
                    "confidence": 72,
                })
                break

    # Find equal lows
    for i in range(len(lows)):
        for j in range(i + 3, len(lows)):
            if abs(lows[i] - lows[j]) / close < LIQUIDITY_TOLERANCE:
                level = (lows[i] + lows[j]) / 2
                levels.append({
                    "type": "LIQUIDITY",
                    "subtype": "EQUAL_LOWS",
                    "level": float(level),
                    "confidence": 72,
                })
                break

    # Return top 4 closest to current price
    levels = sorted(levels, key=lambda x: abs(x["level"] - float(close)))[:4]
    return levels


def detect_all_patterns(timeframes: dict) -> dict:
    """
    Run all pattern detectors on H4, H1 and M15.
    Returns a balanced mix across timeframes so the AI sees the full picture.
    Each timeframe contributes its own bucket — no single timeframe crowds out others.
    Returns {"patterns": [...], "liquidity": [...]}
    """
    patterns_by_tf = {}
    liquidity_by_tf = {}

    for tf in ["H4", "H1", "M15"]:
        if tf not in timeframes:
            continue
        df = timeframes[tf]

        obs = detect_order_blocks(df)
        fvgs = detect_fair_value_gaps(df)
        bos = detect_break_of_structure(df)
        liq = detect_liquidity_levels(df)

        tf_patterns = []
        for ob in obs:
            ob["timeframe"] = tf
            tf_patterns.append(ob)
        for fvg in fvgs:
            fvg["timeframe"] = tf
            tf_patterns.append(fvg)
        for b in bos:
            b["timeframe"] = tf
            tf_patterns.append(b)
        for l in liq:
            l["timeframe"] = tf

        patterns_by_tf[tf] = tf_patterns
        liquidity_by_tf[tf] = liq

    # Build balanced output: up to 4 patterns per timeframe (H4, H1, M15) = max 12
    # Priority order within each TF: BOS first (highest signal), then OB, then FVG
    def sort_key(p):
        order = {"BREAK_OF_STRUCTURE": 0, "ORDER_BLOCK": 1, "FAIR_VALUE_GAP": 2}
        return order.get(p["type"], 3)

    final_patterns = []
    per_tf_limit = 4
    for tf in ["H4", "H1", "M15"]:
        bucket = sorted(patterns_by_tf.get(tf, []), key=sort_key)
        final_patterns.extend(bucket[:per_tf_limit])

    # Liquidity: 2 per timeframe = 6 total
    final_liquidity = []
    for tf in ["H4", "H1", "M15"]:
        final_liquidity.extend(liquidity_by_tf.get(tf, [])[:2])

    return {
        "patterns": final_patterns,
        "liquidity": final_liquidity,
    }
