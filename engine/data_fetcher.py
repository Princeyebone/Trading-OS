"""
engine/data_fetcher.py — OHLCV data fetching for XAU/USD using adapter pattern.

Pulls M15, H1, H4 candles. Validates staleness.
Returns pandas DataFrames indexed by datetime.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
import pandas as pd

from app.settings import settings

logger = logging.getLogger(__name__)

STALENESS_MINUTES = 20   # if latest candle is older than this → SKIP

_cache: dict = {}   # simple in-memory cache {timeframe: (fetched_at, df)}
CACHE_TTL_SECONDS = 60 * 10  # 10 minutes

_fetcher_instance = None

def get_fetcher():
    """Factory to get the configured fetcher instance."""
    global _fetcher_instance
    if _fetcher_instance is not None:
        return _fetcher_instance

    mode = getattr(settings, "data_feed_mode", "yfinance").lower()
    
    if mode == "mt5":
        logger.info("Initializing DataFetcher adapter for MT5")
        from engine.adapters.mt5_fetcher import MT5Fetcher
        _fetcher_instance = MT5Fetcher()
    else:
        logger.info("Initializing DataFetcher adapter for yfinance")
        from engine.adapters.yfinance_fetcher import YFinanceFetcher
        _fetcher_instance = YFinanceFetcher()
        
    return _fetcher_instance


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

    fetcher = get_fetcher()
    df = fetcher.fetch_ohlcv(timeframe)

    if df is None or df.empty:
        return None

    _cache[timeframe] = (now, df)
    return df


def check_staleness(df: pd.DataFrame) -> bool:
    """
    Returns True (is_stale) if the latest candle is older than STALENESS_MINUTES.
    """
    if df is None or df.empty:
        return True
    if settings.ignore_staleness:
        return False
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


def fetch_all_timeframes() -> tuple[dict, bool]:
    """
    Fetch M15, H1, H4 in one call.
    Returns ({"M15": df, "H1": df, "H4": df}, is_stale) or raises RuntimeError if fetch fails entirely.
    """
    result = {}
    is_stale = False
    for tf in ["M15", "H1", "H4"]:
        df = fetch_ohlcv(tf)
        if df is None:
            raise RuntimeError(f"Failed to fetch {tf} data")
        if check_staleness(df):
            is_stale = True
        result[tf] = df
    return result, is_stale
