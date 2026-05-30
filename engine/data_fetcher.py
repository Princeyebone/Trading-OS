"""
engine/data_fetcher.py — yfinance OHLCV data fetching for XAU/USD.

Pulls M15, H1, H4 candles. Validates staleness.
Returns pandas DataFrames indexed by datetime.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

SYMBOL = "GC=F"          # yfinance ticker for Gold Futures (XAU/USD proxy)
STALENESS_MINUTES = 20   # if latest candle is older than this → SKIP

# Interval strings for yfinance
INTERVAL_MAP = {
    "M15": "15m",
    "H1":  "60m",
    "H4":  "1h",   # will resample H1 to H4
}

# How many bars to fetch per timeframe
BARS_NEEDED = {
    "M15": 200,   # ~2 days of M15
    "H1":  200,   # ~8 days of H1
    "H4":  200,   # ~33 days of H4
}

_cache: dict = {}   # simple in-memory cache {timeframe: (fetched_at, df)}
CACHE_TTL_SECONDS = 60 * 10  # 10 minutes


def _fetch_raw(interval: str, period: str) -> Optional[pd.DataFrame]:
    """Download OHLCV from yfinance."""
    try:
        ticker = yf.Ticker(SYMBOL)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            logger.warning(f"yfinance returned empty DataFrame for interval={interval}")
            return None
        df.index = pd.to_datetime(df.index, utc=True)
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.error(f"yfinance fetch error: {e}")
        return None


def _resample_to_h4(h1_df: pd.DataFrame) -> pd.DataFrame:
    """Resample H1 data to H4 OHLCV."""
    df = h1_df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return df


def fetch_ohlcv(timeframe: str, use_cache: bool = True) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV for the given timeframe ("M15", "H1", "H4").
    Returns DataFrame or None if fetch failed / data is stale.
    """
    now = datetime.now(timezone.utc)

    # Cache hit
    if use_cache and timeframe in _cache:
        cached_at, df = _cache[timeframe]
        age_secs = (now - cached_at).total_seconds()
        if age_secs < CACHE_TTL_SECONDS:
            return df

    if timeframe == "M15":
        df = _fetch_raw("15m", "5d")
    elif timeframe == "H1":
        df = _fetch_raw("1h", "30d")
    elif timeframe == "H4":
        h1 = _fetch_raw("1h", "60d")
        df = _resample_to_h4(h1) if h1 is not None else None
    else:
        logger.error(f"Unknown timeframe: {timeframe}")
        return None

    if df is None or df.empty:
        return None

    # Tail to BARS_NEEDED
    df = df.tail(BARS_NEEDED.get(timeframe, 200))

    _cache[timeframe] = (now, df)
    return df


def check_staleness(df: pd.DataFrame) -> bool:
    """
    Returns True (is_stale) if the latest candle is older than STALENESS_MINUTES.
    """
    if df is None or df.empty:
        return True
    latest_candle_time = df.index[-1].to_pydatetime()
    if latest_candle_time.tzinfo is None:
        latest_candle_time = latest_candle_time.replace(tzinfo=timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - latest_candle_time).total_seconds() / 60
    return age_minutes > STALENESS_MINUTES


def get_current_price() -> Optional[float]:
    """Get the latest close price for XAU/USD."""
    df = fetch_ohlcv("M15")
    if df is None or df.empty:
        return None
    return float(df["close"].iloc[-1])


def fetch_all_timeframes() -> dict:
    """
    Fetch M15, H1, H4 in one call.
    Returns {"M15": df, "H1": df, "H4": df} or raises if any is stale.
    """
    result = {}
    for tf in ["M15", "H1", "H4"]:
        df = fetch_ohlcv(tf)
        if df is None:
            raise RuntimeError(f"Failed to fetch {tf} data")
        if check_staleness(df):
            raise RuntimeError(f"{tf} data is stale — latest candle too old")
        result[tf] = df
    return result
