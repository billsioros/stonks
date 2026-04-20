# Vulture whitelist for methods that are used in tests or intended for public API
from stonks.cache import LocalCache
from stonks.store import SQLiteStore

LocalCache.delete
SQLiteStore.get_screen
SQLiteStore.is_in_watchlist
