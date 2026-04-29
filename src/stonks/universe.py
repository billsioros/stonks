"""UniverseLoader — loads the stock symbol list from Finnhub."""

import logging
import time
from typing import Any

import finnhub  # type: ignore[import-untyped]
import pandas as pd  # type: ignore[import-untyped]

from stonks.config import (
    DEFAULT_EXCHANGE,
    FINNHUB_API_KEY,
    SYMBOLS_CACHE_TTL,
)

logger = logging.getLogger(__name__)

# Module-level cache: exchange -> (timestamp, data)
_symbols_cache: dict[str, tuple[float, Any]] = {}


class UniverseLoader:
    """Loads and caches the list of tradeable symbols from Finnhub."""

    def __init__(
        self,
        api_key: str = FINNHUB_API_KEY,
    ) -> None:
        self._client = finnhub.Client(api_key=api_key)

    def load_symbols(
        self,
        exchange: str = DEFAULT_EXCHANGE,
        security_type: str | None = None,
    ) -> pd.DataFrame:
        """Return a DataFrame of symbols for the given exchange."""
        global _symbols_cache

        now = time.time()
        if exchange in _symbols_cache:
            cached_time, cached_data = _symbols_cache[exchange]
            if now - cached_time < SYMBOLS_CACHE_TTL:
                logger.info(
                    "Loaded %d symbols from memory for %s", len(cached_data), exchange
                )
                df = pd.DataFrame(cached_data)
            else:
                del _symbols_cache[exchange]
                df = pd.DataFrame()
        else:
            df = pd.DataFrame()

        if df.empty:
            logger.info("Fetching symbols from Finnhub for exchange=%s", exchange)
            try:
                raw = self._client.stock_symbols(exchange)
            except Exception as e:
                logger.error("Failed to fetch symbols for %s: %s", exchange, e)
                return pd.DataFrame()

            if not raw:
                return pd.DataFrame()

            _symbols_cache[exchange] = (now, raw)
            logger.info("Fetched and cached %d symbols for %s", len(raw), exchange)
            df = pd.DataFrame(raw)

        col_map = {
            "displaySymbol": "display_symbol",
            "shareClassFIGI": "share_class_figi",
        }
        df = df.rename(columns=col_map)

        if security_type and "type" in df.columns:
            df = df[df["type"] == security_type]

        return df.reset_index(drop=True)

    def get_common_stocks(self, exchange: str = DEFAULT_EXCHANGE) -> pd.DataFrame:
        """Convenience: return only common stocks."""
        return self.load_symbols(exchange=exchange, security_type="Common Stock")
