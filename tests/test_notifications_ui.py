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


def _run_app(
    db_path: Path, monkeypatch, *, session_state: dict[str, object] | None = None
) -> AppTest:
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    # Most notification tests seed only a few rows, so bypass the default
    # quality screen that would otherwise filter them all out.
    initial_state = {"active_filters": {}, **(session_state or {})}
    for key, value in initial_state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_buy_opportunities_live_in_a_collapsed_notifications_expander_above_masthead(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "BOTH", "description": "Below both estimates"}])
    seeded.add_alert(
        "BOTH",
        "buy_opportunity",
        "good",
        "Near its 52-week low",
        "Price 101.00 vs 52w low 100.00",
        "BOTH:buy_opportunity:test",
    )
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
    seeded.replace_stocks([{"symbol": "BOTH", "description": "Below both estimates"}])
    seeded.add_alert(
        "BOTH",
        "buy_opportunity",
        "good",
        "Buy opportunity",
        "Below DCF and Lynch",
        "BOTH:buy_opportunity:test",
    )
    seeded.add_alert(
        "BOTH",
        "buy_opportunity",
        "good",
        "Buy opportunity",
        "Below DCF and Lynch",
        "BOTH:buy_opportunity:other-test",
    )

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    labels = [button.label for button in notification.button]

    assert labels.count("BOTH ▸") == 1


def test_notifications_come_from_stored_alerts_not_live_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks(
        [
            {
                "symbol": "SNAP",
                "description": "Near low",
                "price": 101.0,
                "week_52_low": 100.0,
                "dcf_fair_value": None,
                "lynch_fair_value": None,
            }
        ]
    )
    at = _run_app(db_path, monkeypatch)
    assert not [item for item in at.expander if "Notifications" in item.label]

    seeded.add_alert(
        "SNAP",
        "buy_opportunity",
        "good",
        "Near its 52-week low",
        "Price 101.00 vs 52w low 100.00",
        "SNAP:buy_opportunity:test",
    )
    at = _run_app(db_path, monkeypatch)
    notification = next(item for item in at.expander if "Notifications" in item.label)
    assert "SNAP ▸" in [b.label for b in notification.button]
    assert any("buy opportunities" in str(item.value) for item in at.success)


def test_notifications_hide_non_screener_symbols_unless_watchlisted(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks(
        [
            {"symbol": "SCREEN", "description": "In the active screen"},
            {"symbol": "OUT", "description": "In the database, outside the screen"},
        ]
    )
    seeded.add_alert(
        "SCREEN",
        "off_high",
        "good",
        "Screener alert",
        "In the current universe",
        "SCREEN:off_high:test",
    )
    seeded.add_alert(
        "OUT",
        "off_high",
        "good",
        "Filtered-out alert",
        "In the database, not the active screen",
        "OUT:off_high:test",
    )
    seeded.add_alert(
        "GHOST",
        "off_high",
        "good",
        "Stale alert",
        "No longer in the database",
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

    at = _run_app(
        db_path,
        monkeypatch,
        session_state={"active_filters": {"symbol": {"values": ["SCREEN"]}}},
    )

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    labels = [button.label for button in notification.button]
    text = " ".join(
        str(getattr(value, "value", value))
        for value in [*notification.markdown, *notification.caption]
    )

    assert "SCREEN ▸" in labels
    assert "WATCHONLY ▸" in labels
    assert "OUT ▸" not in labels
    assert "OUT" not in text
    assert "GHOST ▸" not in labels
    assert "GHOST" not in text
    assert "Notifications (2)" in notification.label

    # Nothing outside the visible screener/watchlist may surface elsewhere.
    all_labels = [button.label for button in at.button]
    assert "OUT ▸" not in all_labels
    assert "GHOST ▸" not in all_labels
    assert not any("Watchlist (" in tab.label for tab in at.tabs)


def test_notifications_group_alerts_by_symbol(tmp_path: Path, monkeypatch) -> None:
    """Alerts for one ticker share a card, so the badge counts tickers."""
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks(
        [
            {"symbol": "NVDA", "description": "Nvidia"},
            {"symbol": "AMD", "description": "AMD"},
        ]
    )
    for index, title in enumerate(
        [
            "AI Buildout Echoes the 1990s",
            "Why Nvidia, Micron, and SpaceX Stocks Keep Tumbling",
            "Chip Stocks Pull Back Again",
        ]
    ):
        seeded.add_alert(
            "NVDA",
            "news",
            "info",
            title,
            "ETF Trends" if index == 0 else "TipRanks",
            f"NVDA:news:{index}",
        )
    seeded.add_alert(
        "AMD",
        "off_high",
        "warn",
        "AMD pulled back",
        "10% off high",
        "AMD:off_high:test",
    )

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    assert notification.label == "🔔 Notifications (2)"
    labels = [button.label for button in notification.button]
    assert labels.count("NVDA ▸") == 1
    assert labels.count("AMD ▸") == 1


def test_notifications_show_more_than_the_store_default_limit(
    tmp_path: Path, monkeypatch
) -> None:
    """A broad sync can leave more unread alerts than the store's default page."""
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    symbols = [f"SYM{index:02d}" for index in range(55)]
    seeded.replace_stocks(
        [{"symbol": symbol, "description": symbol} for symbol in symbols]
    )
    for symbol in symbols:
        seeded.add_alert(
            symbol,
            "buy_opportunity",
            "good",
            "Near its 52-week low",
            None,
            f"{symbol}:buy_opportunity:test",
        )
    assert len(seeded.get_alerts()) == 50
    assert len(seeded.get_alerts(limit=None)) == 55

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    assert notification.label == "🔔 Notifications (55)"
    labels = [button.label for button in notification.button]
    assert all(f"{symbol} ▸" in labels for symbol in symbols)
    assert any("55 unread alerts" in str(item.value) for item in at.info)


def test_notifications_merge_a_screener_buy_with_alerts_for_the_same_symbol(
    tmp_path: Path, monkeypatch
) -> None:
    """A stored buy signal and its alerts belong to one ticker card."""
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "BOTH", "description": "Below both estimates"}])
    seeded.add_alert(
        "BOTH",
        "buy_opportunity",
        "good",
        "Near its 52-week low",
        "Price 101.00 vs 52w low 100.00",
        "BOTH:buy_opportunity:test",
    )
    seeded.add_alert(
        "BOTH", "news", "info", "First headline", "TipRanks", "BOTH:news:1"
    )
    seeded.add_alert(
        "BOTH", "news", "info", "Second headline", "ETF Trends", "BOTH:news:2"
    )

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    assert notification.label == "🔔 Notifications (1)"
    labels = [button.label for button in notification.button]
    assert labels.count("BOTH ▸") == 1


def test_notifications_group_header_shows_the_strongest_severity(
    tmp_path: Path, monkeypatch
) -> None:
    """A warning in a group is visible before reading its individual lines."""
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "NVDA", "description": "Nvidia"}])
    seeded.add_alert("NVDA", "news", "info", "A headline", "TipRanks", "NVDA:news:1")
    seeded.add_alert(
        "NVDA", "daily_move", "warn", "Down 8.3%", "155.38 → 142.46", "NVDA:move:1"
    )

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    header = str(notification.markdown[0].value)
    assert "🟠" in header
    assert "NVDA" in header


def test_notifications_group_header_tolerates_unknown_severity(
    tmp_path: Path, monkeypatch
) -> None:
    """An unfamiliar severity still renders the ticker card."""
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "NVDA", "description": "Nvidia"}])
    seeded.add_alert(
        "NVDA", "custom", "mystery", "A headline", "TipRanks", "NVDA:custom:1"
    )

    at = _run_app(db_path, monkeypatch)

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    assert "NVDA" in str(notification.markdown[0].value)
    seen = [button for button in notification.button if button.label == "✓"]
    assert seen
    assert seen[0].help == "Mark as seen"


def test_notifications_show_holdings_outside_the_active_screen(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks(
        [
            {"symbol": "SCREEN", "description": "In the active screen"},
            {"symbol": "VUAA", "description": "Held ETF", "type": "ETF"},
        ]
    )
    seeded.add_position("VUAA", 1, 100.0)
    seeded.add_alert("VUAA", "news", "info", "ETF headline", None, "VUAA:news:test")

    at = _run_app(
        db_path,
        monkeypatch,
        session_state={"active_filters": {"symbol": {"values": ["SCREEN"]}}},
    )

    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    text = " ".join(
        str(getattr(value, "value", value))
        for value in [*notification.markdown, *notification.caption]
    )
    assert "VUAA" in text
    assert "in portfolio" in text


def test_mark_one_alert_seen_leaves_other_alerts_unread(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks(
        [
            {"symbol": "NVDA", "description": "Nvidia"},
            {"symbol": "AMD", "description": "AMD"},
        ]
    )
    seeded.add_alert("NVDA", "news", "info", "Old headline", "TipRanks", "NVDA:news:1")
    seeded.add_alert(
        "AMD", "off_high", "warn", "AMD pullback", "10% off high", "AMD:off_high:1"
    )
    seeded.add_alert(
        "NVDA", "news", "info", "New headline", "ETF Trends", "NVDA:news:2"
    )
    ids = [a["id"] for a in seeded.get_alerts()]

    at = _run_app(db_path, monkeypatch)
    notification = next(item for item in at.expander if "Notifications" in item.label)
    next(b for b in notification.button if b.label == "✓").click().run()

    assert [a["id"] for a in seeded.get_alerts()] == ids[1:]
    at = _run_app(db_path, monkeypatch)
    notification = next(item for item in at.expander if "Notifications" in item.label)
    assert "New headline" not in str(notification.markdown[-1].value)
