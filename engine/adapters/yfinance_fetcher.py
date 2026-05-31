import logging
from typing import Optional
import yfinance as yf
import pandas as pd

from app.settings import settings
from engine.adapters.base_fetcher import BaseDataFetcher

logger = logging.getLogger(__name__)

class YFinanceFetcher(BaseDataFetcher):
    def __init__(self, default_symbol: str = "GC=F"):
        self.default_symbol = default_symbol
        
        # How many bars to fetch per timeframe (internal to yfinance to get enough data)
        self.bars_needed = {
            "M15": 200,   # ~2 days of M15
            "H1":  200,   # ~8 days of H1
            "H4":  200,   # ~33 days of H4
        }

    def _get_symbol(self) -> str:
        override = (settings.force_symbol or "").strip()
        if override:
            # We don't want to spam warnings on every single fetch call, so we'll just return it.
            # (Warning is already handled at engine startup or higher up if needed)
            return override
        return self.default_symbol

    def _fetch_raw(self, interval: str, period: str) -> Optional[pd.DataFrame]:
        symbol = self._get_symbol()
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval, auto_adjust=True)
            if df.empty:
                logger.warning(f"yfinance returned empty DataFrame for symbol={symbol} interval={interval}")
                return None
            df.index = pd.to_datetime(df.index, utc=True)
            df.columns = [c.lower() for c in df.columns]
            return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.error(f"yfinance fetch error (symbol={symbol}): {e}")
            return None

    def _resample_to_h4(self, h1_df: pd.DataFrame) -> pd.DataFrame:
        df = h1_df.resample("4h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()
        return df

    def fetch_ohlcv(self, timeframe: str) -> Optional[pd.DataFrame]:
        if timeframe == "M15":
            df = self._fetch_raw("15m", "5d")
        elif timeframe == "H1":
            df = self._fetch_raw("1h", "30d")
        elif timeframe == "H4":
            h1 = self._fetch_raw("1h", "60d")
            df = self._resample_to_h4(h1) if h1 is not None else None
        else:
            logger.error(f"Unknown timeframe: {timeframe}")
            return None

        if df is None or df.empty:
            return None

        # Tail to BARS_NEEDED
        df = df.tail(self.bars_needed.get(timeframe, 200))
        return df
