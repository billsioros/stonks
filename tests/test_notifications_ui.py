"""AppTest coverage for the top-level notifications surface."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app
from stonks.store import SQLiteStore


@pytest.fixture(autouse=True)
def _clear_resource_cache_after_each_test() -> None:
    """Prevent a temp-DB AppTest from leaking its cached store into later tests."""
    yield
    st.cache_resource.clear()


def _run_app(db_path: Path, monkeypatch) -> AppTest:
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def _seed_opportunities(store: SQLiteStore) -> None:
    store.replace_stocks(
        [
            {
                "symbol": "BOTH",
                "description": "Below both estimates",
                "price": 101.0,
                "week_52_low": 100.0,
                "dcf_fair_value": 120.0,
                "lynch_fair_value": 130.0,
            },
            {
                "symbol": "LOW",
                "description": "Near the low only",
                "price": 101.0,
                "week_52_low": 100.0,
                "dcf_fair_value": None,
                "lynch_fair_value": None,
            },
        ]
    )


def test_buy_opportunities_live_in_a_collapsed_notifications_expander_above_masthead(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    _seed_opportunities(seeded)
    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    assert notification.proto.expanded is False

    text = " ".join(
        str(getattr(value, "value", value))
        for value in [*notification.markdown, *notification.caption]
    )
    assert "52w low" in text.lower()

    children = at._tree.root.children[0].children
    notification_index = next(
        index
        for index, child in children.items()
        if getattr(child, "label", "") == notification.label
    )
    masthead_index = next(
        index
        for index, child in children.items()
        if '<div class="sk-head"' in str(getattr(child, "value", ""))
    )
    assert notification_index < masthead_index


def test_notifications_deduplicate_persisted_buy_opportunity_alerts(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    _seed_opportunities(seeded)
    seeded.add_alert(
        "BOTH",
        "buy_opportunity",
        "good",
        "Buy opportunity",
        "Below DCF and Lynch",
        "BOTH:buy_opportunity:test",
    )

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    labels = [button.label for button in notification.button]

    assert labels.count("BOTH ▸") == 1
    assert labels.count("LOW ▸") == 1


def test_notifications_hide_non_screener_symbols_unless_watchlisted(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "SCREEN", "description": "In the screener"}])
    seeded.add_alert(
        "SCREEN",
        "off_high",
        "good",
        "Screener alert",
        "In the current universe",
        "SCREEN:off_high:test",
    )
    seeded.add_alert(
        "GHOST",
        "off_high",
        "good",
        "Stale alert",
        "No longer in the screener",
        "GHOST:off_high:test",
    )
    seeded.add_alert(
        "WATCHONLY",
        "off_high",
        "good",
        "Watchlist alert",
        "Tracked outside the screener",
        "WATCHONLY:off_high:test",
    )
    seeded.add_to_watchlist("WATCHONLY")

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    labels = [button.label for button in notification.button]
    text = " ".join(
        str(getattr(value, "value", value))
        for value in [*notification.markdown, *notification.caption]
    )

    assert "SCREEN ▸" in labels
    assert "WATCHONLY ▸" in labels
    assert "GHOST ▸" not in labels
    assert "GHOST" not in text
    assert "Notifications (2)" in notification.label
