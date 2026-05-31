import logging
from typing import Optional
import pandas as pd
from datetime import timezone

from app.settings import settings
from engine.adapters.base_fetcher import BaseDataFetcher
from engine.broker_executor import _init_mt5

logger = logging.getLogger(__name__)

class MT5Fetcher(BaseDataFetcher):
    def __init__(self, default_symbol: str = "XAUUSD"):
        self.default_symbol = default_symbol
        self.bars_needed = {
            "M15": 200,
            "H1":  200,
            "H4":  200,
        }

    def _get_symbol(self) -> str:
        override = (settings.force_symbol or "").strip()
        if override:
            return override
        return self.default_symbol

    def fetch_ohlcv(self, timeframe: str) -> Optional[pd.DataFrame]:
        import MetaTrader5 as mt5

        if not _init_mt5():
            logger.error("MT5 not initialized. Cannot fetch data.")
            return None

        symbol = self._get_symbol()

        # Map string timeframe to MT5 constant
        if timeframe == "M15":
            mt5_tf = mt5.TIMEFRAME_M15
        elif timeframe == "H1":
            mt5_tf = mt5.TIMEFRAME_H1
        elif timeframe == "H4":
            mt5_tf = mt5.TIMEFRAME_H4
        else:
            logger.error(f"Unknown timeframe for MT5: {timeframe}")
            return None

        count = self.bars_needed.get(timeframe, 200)

        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            logger.error(f"MT5 returned no data for symbol={symbol} timeframe={timeframe}")
            return None

        df = pd.DataFrame(rates)
        # MT5 returns time as posix timestamp
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df.set_index('time', inplace=True)
        
        # MT5 columns: time, open, high, low, close, tick_volume, spread, real_volume
        # We need open, high, low, close, volume
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        
        return df[["open", "high", "low", "close", "volume"]]
