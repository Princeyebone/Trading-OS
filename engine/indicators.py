"""
engine/indicators.py — Technical indicator computation using the `ta` library.

Computes: EMA 20/50/200, RSI 14, ATR 14, MACD, Stochastic.
Also computes ATR percentile (30-day rolling) and EMA alignment.
"""
import logging
from typing import Optional
import pandas as pd
import ta

logger = logging.getLogger(__name__)


# ─── EMA ──────────────────────────────────────────────────────────────────────
def compute_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA 20, 50, 200 columns to DataFrame."""
    df = df.copy()
    df["ema_20"]  = ta.trend.ema_indicator(df["close"], window=20)
    df["ema_50"]  = ta.trend.ema_indicator(df["close"], window=50)
    df["ema_200"] = ta.trend.ema_indicator(df["close"], window=200)
    return df


def get_ema_alignment(df: pd.DataFrame) -> str:
    """
    Returns 'BULLISH', 'BEARISH', or 'MIXED' based on latest EMA stacking.
    BULLISH: price > EMA20 > EMA50 > EMA200
    BEARISH: price < EMA20 < EMA50 < EMA200
    """
    row = df.iloc[-1]
    price = row["close"]
    try:
        ema20, ema50, ema200 = row["ema_20"], row["ema_50"], row["ema_200"]
        if price > ema20 > ema50 > ema200:
            return "BULLISH"
        elif price < ema20 < ema50 < ema200:
            return "BEARISH"
        else:
            return "MIXED"
    except (KeyError, TypeError):
        return "MIXED"


# ─── RSI ──────────────────────────────────────────────────────────────────────
def compute_rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    df = df.copy()
    df["rsi"] = ta.momentum.rsi(df["close"], window=window)
    return df


# ─── ATR ──────────────────────────────────────────────────────────────────────
def compute_atr(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    df = df.copy()
    df["atr"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=window
    )
    return df


def get_current_atr(timeframe: str = "M15") -> Optional[float]:
    """Fetch current ATR directly via data_fetcher without full evaluation loop."""
    from engine.data_fetcher import fetch_ohlcv
    df = fetch_ohlcv(timeframe)
    if df is None or df.empty:
        return None
    if "atr" not in df.columns:
        df = compute_atr(df)
    return float(df["atr"].iloc[-1])



def get_atr_percentile(df: pd.DataFrame, lookback: int = 30 * 4) -> float:
    """
    Compute current ATR's percentile rank over the last `lookback` bars.
    Default 30*4 = 120 H4 bars ≈ 30 days.
    """
    if "atr" not in df.columns:
        df = compute_atr(df)
    recent_atrs = df["atr"].dropna().tail(lookback)
    if len(recent_atrs) < 2:
        return 50.0
    current_atr = recent_atrs.iloc[-1]
    percentile = (recent_atrs < current_atr).mean() * 100
    return round(float(percentile), 1)


# ─── MACD ─────────────────────────────────────────────────────────────────────
def compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    macd = ta.trend.MACD(df["close"])
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()
    return df


# ─── Stochastic ────────────────────────────────────────────────────────────────
def compute_stochastic(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    stoch = ta.momentum.StochasticOscillator(df["high"], df["low"], df["close"])
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()
    return df


# ─── Volume ratio ──────────────────────────────────────────────────────────────
def compute_volume_ratio(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Ratio of current volume to N-bar moving average volume."""
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(window=window).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma"]
    return df


# ─── Main compute function ─────────────────────────────────────────────────────
def compute_all_indicators(timeframes: dict) -> dict:
    """
    Given {"M15": df, "H1": df, "H4": df}, compute all indicators on each.
    Returns enriched dict with same keys.
    """
    result = {}
    for tf, df in timeframes.items():
        df = compute_emas(df)
        df = compute_rsi(df)
        df = compute_atr(df)
        df = compute_macd(df)
        df = compute_stochastic(df)
        df = compute_volume_ratio(df)
        result[tf] = df

    return result


def extract_indicator_snapshot(timeframes: dict) -> dict:
    """
    Extract the latest indicator values from each timeframe into a flat dict
    for prompt building and DB storage. Includes human-readable interpretations
    (directions, signals) to optimise LLM token usage and reasoning quality.
    """
    snap = {}
    for tf, df in timeframes.items():
        if len(df) < 4:
            continue
            
        row = df.iloc[-1]
        prefix = tf.lower()
        
        # Raw prices & core averages
        snap[f"{prefix}_close"]     = round(float(row["close"]), 2)
        snap[f"{prefix}_ema_20"]    = round(float(row.get("ema_20", 0)), 2)
        snap[f"{prefix}_ema_50"]    = round(float(row.get("ema_50", 0)), 2)
        snap[f"{prefix}_ema_200"]   = round(float(row.get("ema_200", 0)), 2)
        snap[f"{prefix}_alignment"] = get_ema_alignment(df)
        
        # EMA Slope (Momentum of the structure over last 4 candles)
        try:
            slope = row["ema_20"] - df.iloc[-4]["ema_20"]
            snap[f"{prefix}_ema20_slope"] = round(float(slope), 2)
        except Exception:
            snap[f"{prefix}_ema20_slope"] = 0.0

        # RSI + Direction
        rsi_val = float(row.get("rsi", 50))
        snap[f"{prefix}_rsi"] = round(rsi_val, 1)
        try:
            rsi_prev = float(df.iloc[-3]["rsi"])
            snap[f"{prefix}_rsi_direction"] = "RISING" if rsi_val > rsi_prev else "FALLING"
        except Exception:
            snap[f"{prefix}_rsi_direction"] = "UNKNOWN"

        # Stochastic + Crossover Signal
        stoch_k = float(row.get("stoch_k", 50))
        stoch_d = float(row.get("stoch_d", 50))
        snap[f"{prefix}_stoch_k"] = round(stoch_k, 1)
        snap[f"{prefix}_stoch_d"] = round(stoch_d, 1)
        snap[f"{prefix}_stoch_signal"] = "BULLISH_CROSS" if stoch_k > stoch_d else "BEARISH_CROSS"

        # MACD + Momentum Interpretation
        macd_hist = float(row.get("macd_hist", 0))
        snap[f"{prefix}_macd_hist"] = round(macd_hist, 4)
        try:
            macd_prev = float(df.iloc[-2]["macd_hist"])
            snap[f"{prefix}_macd_momentum"] = "INCREASING" if macd_hist > macd_prev else "DECREASING"
        except Exception:
            snap[f"{prefix}_macd_momentum"] = "UNKNOWN"

        # Volume + Signal
        vol_ratio = float(row.get("vol_ratio", 1))
        snap[f"{prefix}_vol_ratio"] = round(vol_ratio, 2)
        if vol_ratio > 1.5:
            snap[f"{prefix}_volume_signal"] = "HIGH"
        elif vol_ratio < 0.8:
            snap[f"{prefix}_volume_signal"] = "LOW"
        else:
            snap[f"{prefix}_volume_signal"] = "NORMAL"

        # ATR
        snap[f"{prefix}_atr"] = round(float(row.get("atr", 0)), 2)

    # Cross-timeframe macro attributes
    if "H4" in timeframes:
        snap["h4_atr_percentile"] = get_atr_percentile(timeframes["H4"], lookback=120)
        # Keep backwards compatibility for any hardcoded references
        snap["atr_percentile"] = snap["h4_atr_percentile"]
    if "H1" in timeframes:
        snap["h1_atr_percentile"] = get_atr_percentile(timeframes["H1"], lookback=120)

    return snap

