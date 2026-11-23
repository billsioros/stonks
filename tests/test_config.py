import pytest

from stonks.config import NUMERIC_FILTER_COLUMNS
from stonks.store import SQLiteStore


def test_config_columns_are_backed_by_store_schema(tmp_path):
    from stonks.config import COLUMN_DISPLAY_NAMES, VIEW_PRESETS

    store = SQLiteStore(tmp_path / "config.db")
    with store._connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}

    assert set(COLUMN_DISPLAY_NAMES) <= columns
    assert {c for cols in VIEW_PRESETS.values() for c in cols} <= set(
        COLUMN_DISPLAY_NAMES
    )
    assert set(NUMERIC_FILTER_COLUMNS) <= columns


def test_every_displayed_column_has_a_help_text():
    from stonks.config import COLUMN_HELP, COLUMN_DISPLAY_NAMES

    missing = sorted(set(COLUMN_DISPLAY_NAMES) - set(COLUMN_HELP))
    assert missing == []
    assert all(text.strip() for text in COLUMN_HELP.values())


@pytest.mark.parametrize("column", NUMERIC_FILTER_COLUMNS)
def test_all_numeric_filter_columns_are_filterable(tmp_path, column):
    store = SQLiteStore(tmp_path / "config.db")
    store.save_stock("LOW", {column: 1.0})
    store.save_stock("HIGH", {column: 10.0})

    rows, _, _ = store.get_stocks(filters={column: {"min": 5}}, page_size=10)

    assert [row["symbol"] for row in rows] == ["HIGH"]
