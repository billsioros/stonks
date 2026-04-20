"""UniverseLoader — loads the stock symbol list from Finnhub."""

from __future__ import annotations

import logging
from typing import Any

import finnhub
import pandas as pd

from stonks.cache import LocalCache
from stonks.config import (
    DEFAULT_EXCHANGE,
    FINNHUB_API_KEY,
    SYMBOLS_CACHE_TTL,
)

logger = logging.getLogger(__name__)


class UniverseLoader:
    """Loads and caches the list of tradeable symbols from Finnhub."""

    def __init__(
        self,
        api_key: str = FINNHUB_API_KEY,
        cache: LocalCache | None = None,
    ) -> None:
        self._client = finnhub.Client(api_key=api_key)
        self._cache = cache or LocalCache()

    def load_symbols(
        self,
        exchange: str = DEFAULT_EXCHANGE,
        security_type: str | None = None,
    ) -> pd.DataFrame:
        """Return a DataFrame of symbols for the given exchange.

        Columns: symbol, description, currency, exchange, mic, type, figi, shareClassFIGI
        """
        cache_key = f"symbols_{exchange}"
        cached = self._cache.get(cache_key, ttl=SYMBOLS_CACHE_TTL)

        if cached is not None:
            logger.info("Loaded %d symbols from cache for %s", len(cached), exchange)
            df = pd.DataFrame(cached)
        else:
            logger.info("Fetching symbols from Finnhub for exchange=%s", exchange)
            raw: list[dict[str, Any]] = self._client.stock_symbols(exchange)
            self._cache.set(cache_key, raw)
            logger.info("Fetched and cached %d symbols for %s", len(raw), exchange)
            df = pd.DataFrame(raw)

        # Normalise column names
        col_map = {
            "displaySymbol": "display_symbol",
            "shareClassFIGI": "share_class_figi",
        }
        df = df.rename(columns=col_map)

        # Filter by security type if requested
        if security_type and "type" in df.columns:
            df = df[df["type"] == security_type]

        return df.reset_index(drop=True)

    def get_common_stocks(self, exchange: str = DEFAULT_EXCHANGE) -> pd.DataFrame:
        """Convenience: return only common stocks."""
        return self.load_symbols(exchange=exchange, security_type="Common Stock")
