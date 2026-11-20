# Vulture whitelist for methods that are used in tests or intended for public API
from stonks.cache import LocalCache

from stonks.stockanalysis import SUPPORTED_COLUMNS
from stonks.store import SQLiteStore

LocalCache.delete  # noqa: B018
SQLiteStore.get_screen  # noqa: B018
SQLiteStore.is_in_watchlist  # noqa: B018
SQLiteStore.get_synced_symbols  # noqa: B018
SQLiteStore.get_stale_symbols  # noqa: B018
SUPPORTED_COLUMNS  # noqa: B018
