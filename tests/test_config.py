def test_config_columns_are_backed_by_store_schema(tmp_path):
    from stonks.config import COLUMN_DISPLAY_NAMES, NUMERIC_FILTER_COLUMNS, VIEW_PRESETS
    from stonks.store import SQLiteStore

    store = SQLiteStore(tmp_path / "config.db")
    with store._connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}

    assert set(COLUMN_DISPLAY_NAMES) <= columns
    assert {c for cols in VIEW_PRESETS.values() for c in cols} <= set(
        COLUMN_DISPLAY_NAMES
    )
    assert set(NUMERIC_FILTER_COLUMNS) <= columns
