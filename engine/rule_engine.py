"""
engine/rule_engine.py — Weighted Scoring TCP Rule Engine

Evaluates price action rules against H4/H1/M15 DataFrames using a 100-point 
scoring system. Signal fires if score >= 70.
"""

import logging
import pandas as pd
import ta

logger = logging.getLogger("engine.rule_engine")

# ─── Shared helpers ────────────────────────────────────────────────────────────

def _ensure_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "ema_20" not in df.columns:
        df["ema_20"] = ta.trend.ema_indicator(df["close"], window=20)
    if "ema_50" not in df.columns:
        df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)
    if "ema_200" not in df.columns:
        df["ema_200"] = ta.trend.ema_indicator(df["close"], window=200)
    if "atr" not in df.columns:
        df["atr"] = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=14
        )
    return df

# ─── Scoring Helpers ──────────────────────────────────────────────────────────

def score_h4_trend(h4: pd.DataFrame, direction: str) -> tuple[int, str]:
    if len(h4) < 20:
        return 0, "INSUFFICIENT_H4"
        
    close = h4["close"]
    ema20 = h4["ema_20"]
    ema50 = h4["ema_50"]
    
    current_price = float(close.iloc[-1])
    current_ema20 = float(ema20.iloc[-1])
    current_ema50 = float(ema50.iloc[-1])
    
    ema_bullish = current_ema20 > current_ema50
    ema_bearish = current_ema20 < current_ema50
    price_above_ema20 = current_price > current_ema20
    price_below_ema20 = current_price < current_ema20
    
    recent_high = float(close.tail(5).max())
    recent_low = float(close.tail(5).min())
    old_high = float(close.iloc[-10:-5].max())
    old_low = float(close.iloc[-10:-5].min())
    higher_highs_lows = recent_high > old_high and recent_low > old_low
    lower_highs_lows = recent_high < old_high and recent_low < old_low
    
    if direction == "BEARISH":
        if ema_bearish and price_below_ema20:
            return 40, "STRONG_BEARISH"
        elif (ema_bearish or price_below_ema20) and lower_highs_lows:
            return 30, "WEAK_BEARISH"
        else:
            return 10, "NEUTRAL"
            
    else: # BULLISH
        if ema_bullish and price_above_ema20:
            return 40, "STRONG_BULLISH"
        elif (ema_bullish or price_above_ema20) and higher_highs_lows:
            return 30, "WEAK_BULLISH"
        else:
            return 10, "NEUTRAL"

def score_h1_pullback(h1: pd.DataFrame, direction: str) -> tuple[int, str]:
    if len(h1) < 12:
        return 0, "INSUFFICIENT_H1"
        
    recent_6_bars = h1.iloc[-6:]
    h1_close = float(h1.iloc[-1]["close"])
    h1_e20 = float(h1.iloc[-1]["ema_20"])
    
    if direction == "BEARISH":
        swing_val = float(recent_6_bars["close"].min())
        bounce = h1_close - swing_val
        
        ema_percent_above = ((h1_close - h1_e20) / h1_e20) * 100 if h1_e20 > 0 else 0
        
        if 3.0 <= bounce <= 50.0 and ema_percent_above <= 0.5:
            return 30, "PERFECT_PULLBACK"
        elif 1.0 <= bounce <= 70.0 and ema_percent_above <= 1.5:
            return 15, "PARTIAL_PULLBACK"
        else:
            if bounce < 1.0: return 0, "NO_BOUNCE"
            if bounce > 70.0: return 0, "OVEREXTENDED"
            return 0, "BROKE_EMA_TOO_FAR"
            
    else: # BULLISH
        swing_val = float(recent_6_bars["close"].max())
        pullback = swing_val - h1_close
        
        ema_percent_below = ((h1_e20 - h1_close) / h1_e20) * 100 if h1_e20 > 0 else 0
        
        if 3.0 <= pullback <= 50.0 and ema_percent_below <= 0.5:
            return 30, "PERFECT_PULLBACK"
        elif 1.0 <= pullback <= 70.0 and ema_percent_below <= 1.5:
            return 15, "PARTIAL_PULLBACK"
        else:
            if pullback < 1.0: return 0, "NO_PULLBACK"
            if pullback > 70.0: return 0, "OVEREXTENDED"
            return 0, "BROKE_EMA_TOO_FAR"

def score_m15_rejection(m15: pd.DataFrame, direction: str) -> tuple[int, str]:
    if len(m15) < 3:
        return 0, "INSUFFICIENT_M15"
        
    current = m15.iloc[-1]
    high = float(current["high"])
    low = float(current["low"])
    close = float(current["close"])
    open_p = float(current["open"])
    
    candle_range = high - low
    body = abs(close - open_p)
    
    last_3 = m15.iloc[-3:]
    
    if direction == "BEARISH":
        # 1. Classic Wick
        if candle_range > 0:
            upper_wick = high - max(open_p, close)
            if upper_wick / candle_range > 0.5:
                return 20, "CLASSIC_WICK"
                
        # 2. Closes logic (2 of 3 bearish)
        bearish_closes = sum(1 for _, row in last_3.iterrows() if float(row["close"]) < float(row["open"]))
        if bearish_closes >= 2:
            return 20, "2_OF_3_CLOSES"
            
        # 3. Doji
        if candle_range > 0 and body / candle_range < 0.3:
            return 10, "DOJI_STALL"
            
    else: # BULLISH
        if candle_range > 0:
            lower_wick = min(open_p, close) - low
            if lower_wick / candle_range > 0.5:
                return 20, "CLASSIC_WICK"
                
        bullish_closes = sum(1 for _, row in last_3.iterrows() if float(row["close"]) > float(row["open"]))
        if bullish_closes >= 2:
            return 20, "2_OF_3_CLOSES"
            
        if candle_range > 0 and body / candle_range < 0.3:
            return 10, "DOJI_STALL"
            
    return 0, "NO_REJECTION"

def score_m15_bos(m15: pd.DataFrame, direction: str) -> tuple[int, str]:
    if len(m15) < 4:
        return 0, "INSUFFICIENT_M15"
        
    current_close = float(m15.iloc[-1]["close"])
    close_3_ago = float(m15.iloc[-4]["close"])
    
    if direction == "BEARISH":
        if current_close < close_3_ago:
            return 10, "BOS_CONFIRMED"
    else:
        if current_close > close_3_ago:
            return 10, "BOS_CONFIRMED"
            
    return 0, "NO_BOS"

# ─── Evaluators ──────────────────────────────────────────────────────────────

def _evaluate_tcp(timeframes: dict, direction: str) -> dict:
    strategy = f"TCP_{direction}_SCORING"
    
    for tf in ("H4", "H1", "M15"):
        if tf not in timeframes or timeframes[tf] is None or len(timeframes[tf]) < 20:
            logger.warning(f"{strategy} | Insufficient {tf} data — SKIP")
            return {"verdict": "WAIT", "strategy": strategy, "reason": f"INSUFFICIENT_{tf}", "rules_checked": {}}

    h4  = _ensure_indicators(timeframes["H4"])
    h1  = _ensure_indicators(timeframes["H1"])
    m15 = _ensure_indicators(timeframes["M15"])
    
    score = 0
    reasons = []
    
    pts_h4, r_h4 = score_h4_trend(h4, direction)
    score += pts_h4
    reasons.append(f"H4:{r_h4}({pts_h4})")
    
    pts_h1, r_h1 = score_h1_pullback(h1, direction)
    score += pts_h1
    reasons.append(f"H1:{r_h1}({pts_h1})")
    
    pts_rej, r_rej = score_m15_rejection(m15, direction)
    score += pts_rej
    reasons.append(f"REJ:{r_rej}({pts_rej})")
    
    pts_bos, r_bos = score_m15_bos(m15, direction)
    score += pts_bos
    reasons.append(f"BOS:{r_bos}({pts_bos})")
    
    # Base signal threshold
    if score < 70:
        return {
            "verdict": "WAIT", "strategy": strategy, 
            "reason": f"LOW_SCORE_{score}", 
            "rules_checked": {"score": score, "breakdown": "|".join(reasons)}
        }
        
    m15_atr = float(m15.iloc[-1].get("atr", 0))
    last_3 = m15.iloc[-3:]
    recent_high = float(last_3["high"].max())
    recent_low  = float(last_3["low"].min())
    if m15_atr <= 0:
        m15_atr = abs(recent_high - recent_low)
        
    entry = float(m15.iloc[-1]["close"])
    sl_dist  = m15_atr * 1.5
    
    if direction == "BEARISH":
        sl = round(recent_high + sl_dist, 2)
    else:
        sl = round(recent_low - sl_dist, 2)
        
    risk = abs(entry - sl)
    
    # We set TP1 to always enforce at least a 1.2 RR ratio based on actual risk
    if direction == "BEARISH":
        tp1 = round(entry - (risk * 1.2), 2)
        tp2 = round(entry - (risk * 2.0), 2)
    else:
        tp1 = round(entry + (risk * 1.2), 2)
        tp2 = round(entry + (risk * 2.0), 2)
        
    reward = abs(tp1 - entry)
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0
    
    # Check if Risk is too enormous (e.g., > 3 ATR) to filter out wild market chop
    if risk > (m15_atr * 3.0):
        return {
            "verdict": "WAIT", "strategy": strategy, 
            "reason": f"RISK_TOO_LARGE_{risk:.2f}", 
            "rules_checked": {"score": score, "breakdown": "|".join(reasons)}
        }

    logger.info(f"SCORING SIGNAL FIRED | {strategy} | score={score} breakdown={'|'.join(reasons)} entry={entry} rr={rr_ratio}")

    return {
        "verdict":    "TRADE",
        "strategy":   strategy,
        "direction":  "SHORT" if direction == "BEARISH" else "LONG",
        "entry":      entry,
        "sl":         sl,
        "tp1":        tp1,
        "tp2":        tp2,
        "rr":         rr_ratio,
        "confidence": score,
        "reason":     "|".join(reasons),
        "rules_checked": {"score": score},
    }

def evaluate_tcp_bearish(timeframes: dict) -> dict:
    return _evaluate_tcp(timeframes, "BEARISH")

def evaluate_tcp_bullish(timeframes: dict) -> dict:
    return _evaluate_tcp(timeframes, "BULLISH")

def evaluate_all(timeframes: dict) -> dict:
    res_b = evaluate_tcp_bearish(timeframes)
    if res_b["verdict"] == "TRADE":
        return res_b
    res_u = evaluate_tcp_bullish(timeframes)
    if res_u["verdict"] == "TRADE":
        return res_u
    return res_b
