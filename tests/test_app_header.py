"""AppTest coverage for the masthead's evidence-backed status badges."""

from __future__ import annotations

import time
from typing import Any

from streamlit.testing.v1 import AppTest

from stonks import app, config, sanity
from stonks.store import SQLiteStore

STALE_SECONDS = config.SYNC_ACTIVE_WINDOW_MINUTES * 60 + 1
FRESH_SECONDS = config.SYNC_ACTIVE_WINDOW_MINUTES * 60 - 1


def _report(results: list[dict[str, Any]], checked_at: float) -> dict[str, Any]:
    return {"checked_at": checked_at, "results": results}


def _sync(status: str | None, success_age: float) -> dict[str, Any]:
    now = time.time()
    info: dict[str, Any] = {}
    if status is not None:
        info["last_sync_status"] = status
        info["last_run"] = now
    if success_age is not None:
        info["last_successful_sync_at"] = now - success_age
    return info


def test_live_sync_state_is_green_only_for_a_recent_success() -> None:
    badge = app.live_sync_state(_sync("success", FRESH_SECONDS))
    assert badge.level == "ok"
    assert badge.label == "Live Sync"
    assert "1h 59m" in badge.detail


def test_live_sync_state_is_red_when_success_is_stale() -> None:
    badge = app.live_sync_state(_sync("success", STALE_SECONDS))
    assert badge.level == "fail"
    assert "121m" in badge.detail or "2h" in badge.detail


def test_failed_last_attempt_overrides_a_recent_success() -> None:
    badge = app.live_sync_state(_sync("failed", FRESH_SECONDS))
    assert badge.level == "fail"
    assert "failed" in badge.detail.lower()


def test_no_sync_is_unknown() -> None:
    badge = app.live_sync_state({})
    assert badge.level == "unknown"
    assert badge.label == "Live Sync"


def test_masthead_shows_both_badges_and_no_hardcoded_sync_claim() -> None:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    assert not at.exception
    html = " ".join(str(md.value) for md in at.markdown)
    assert 'class="sk-badge sk-badge-unknown"' in html
    assert "Live Sync" in html
    assert "Checks pending" in html
    assert "Live Sync Active" not in html


def test_masthead_badges_reflect_a_seeded_report() -> None:
    store = SQLiteStore()
    store.save_metadata(
        sanity.REPORT_KEY,
        sanity.json.dumps(
            _report(
                [{"platform": "StockAnalysis", "ok": False, "detail": "field renamed"}],
                time.time(),
            )
        ),
    )
    try:
        at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
        at.run()
        assert not at.exception
        html = " ".join(str(md.value) for md in at.markdown)
        assert 'class="sk-badge sk-badge-fail"' in html
        assert "StockAnalysis" in html
    finally:
        store.save_metadata(sanity.REPORT_KEY, "")
