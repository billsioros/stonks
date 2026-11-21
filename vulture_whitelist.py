# Vulture whitelist for methods that are used in tests or intended for public API
from stonks.cache import LocalCache

from stonks.stockanalysis import SUPPORTED_COLUMNS
from stonks.store import SQLiteStore

LocalCache.delete  # noqa: B018
SQLiteStore.get_screen  # noqa: B018
SQLiteStore.is_in_watchlist  # noqa: B018
SQLiteStore.get_synced_symbols  # noqa: B018
SQLiteStore.get_stale_symbols  # noqa: B018
SQLiteStore.update_sync_status  # noqa: B018
SQLiteStore.save_stock  # noqa: B018
SQLiteStore.cache_get  # noqa: B018
SQLiteStore.cache_set  # noqa: B018
SQLiteStore.cache_delete  # noqa: B018
SUPPORTED_COLUMNS  # noqa: B018
