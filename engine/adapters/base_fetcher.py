from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

class BaseDataFetcher(ABC):
    """
    Abstract base class for OHLCV data fetchers.
    """

    @abstractmethod
    def fetch_ohlcv(self, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a given timeframe ("M15", "H1", "H4").
        Returns a Pandas DataFrame with columns: open, high, low, close, volume.
        Index must be a timezone-aware (UTC) DatetimeIndex.
        Should return None if fetching fails.
        """
        pass
