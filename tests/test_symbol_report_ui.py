"""AppTest coverage for the single-symbol AI report on the detail page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
from openrouter import errors as or_errors
from streamlit.testing.v1 import AppTest

from stonks.detail import cache_key, resolve_payload
from stonks.dossier import Check, Dossier, Gate
from stonks.store import SQLiteStore

FIXTURES = Path(__file__).parent / "fixtures"


def _seed_overview() -> tuple[SQLiteStore, str]:
    store = SQLiteStore()
    key = cache_key("NVDA", "overview")
    payload = resolve_payload(json.loads((FIXTURES / "nvda_overview.json").read_text()))
    store.cache_set(key, {"data": payload, "fetched_at": 1.0}, ttl_seconds=3600)
    return store, key


def _open_detail() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.session_state["page"] = "detail"
    at.session_state["detail_symbol"] = "NVDA"
    at.run()
    return at


def _debug_toggle(at: AppTest) -> Any:
    return next(toggle for toggle in at.toggle if "Debug" in toggle.label)


def _generate_button(at: AppTest) -> Any:
    return next(button for button in at.button if button.label == "Generate report")


def test_symbol_detail_has_an_opt_in_ai_report() -> None:
    store, key = _seed_overview()
    try:
        at = _open_detail()
        assert not at.exception
        assert [e for e in at.expander if "AI report" in str(e.label)]
        assert any(button.label == "Generate report" for button in at.button)
        assert not [md for md in at.markdown if "## TL;DR" in str(md.value)]
    finally:
        store.cache_delete(key)


def test_debug_builds_and_shows_the_prompt_on_click(monkeypatch: Any) -> None:
    store, key = _seed_overview()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    factory = Mock(return_value="PROMPT-DEBUG")
    send = Mock(return_value="YES")
    monkeypatch.setattr("stonks.report_view.symbol_report_prompt_for", factory)
    monkeypatch.setattr("stonks.report.request_report", send)
    try:
        at = _open_detail()
        _debug_toggle(at).set_value(True).run()
        assert not at.exception
        assert any(code.value == "PROMPT-DEBUG" for code in at.code)
        factory.assert_called_once()
        send.assert_not_called()
    finally:
        store.cache_delete(key)


def test_generate_reuses_the_prompt_built_by_debug(monkeypatch: Any) -> None:
    store, key = _seed_overview()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    factory = Mock(return_value="PROMPT-REUSE")
    send = Mock(return_value="YES")
    monkeypatch.setattr("stonks.report_view.symbol_report_prompt_for", factory)
    monkeypatch.setattr("stonks.report.request_report", send)
    try:
        at = _open_detail()
        _debug_toggle(at).set_value(True).run()
        _generate_button(at).click().run()
        assert not at.exception
        factory.assert_called_once()
        send.assert_called_once()
        assert send.call_args.args[0] == "PROMPT-REUSE"
        assert any(md.value == "YES" for md in at.markdown)
    finally:
        store.cache_delete(key)


def test_debug_reports_a_prompt_build_failure(monkeypatch: Any) -> None:
    store, key = _seed_overview()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    monkeypatch.setattr(
        "stonks.report_view.symbol_report_prompt_for",
        Mock(side_effect=RuntimeError("boom")),
    )
    try:
        at = _open_detail()
        _debug_toggle(at).set_value(True).run()
        assert not at.exception
        assert any("Could not build the prompt" in str(err.value) for err in at.error)
    finally:
        store.cache_delete(key)


def test_debug_shows_prompt_on_the_generate_click(monkeypatch: Any) -> None:
    store, key = _seed_overview()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    monkeypatch.setattr(
        "stonks.report_view.symbol_report_prompt_for",
        lambda _store, _symbol, **_kwargs: "PROMPT-GENERATE",
    )
    monkeypatch.setattr("stonks.report.request_report", lambda *_a, **_k: "YES")
    try:
        at = _open_detail()
        _debug_toggle(at).set_value(True).run()
        _generate_button(at).click().run()
        assert not at.exception
        assert any(code.value == "PROMPT-GENERATE" for code in at.code)
    finally:
        store.cache_delete(key)


def test_debug_shows_prompt_even_when_openrouter_rate_limits(monkeypatch: Any) -> None:
    store, key = _seed_overview()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    monkeypatch.setattr(
        "stonks.report_view.symbol_report_prompt_for",
        lambda _store, _symbol, **_kwargs: "PROMPT-RATE-LIMIT",
    )

    def _raise(*_args: Any, **_kwargs: Any) -> str:
        response = httpx.Response(
            429, request=httpx.Request("POST", "https://openrouter.ai/api/v1")
        )
        raise or_errors.OpenRouterError("failed", response)

    monkeypatch.setattr("stonks.report.request_report", _raise)
    try:
        at = _open_detail()
        _debug_toggle(at).set_value(True).run()
        _generate_button(at).click().run()
        assert any(code.value == "PROMPT-RATE-LIMIT" for code in at.code)
        assert any("rate limit" in str(err.value).lower() for err in at.error)
    finally:
        store.cache_delete(key)


def _dossier() -> Dossier:
    gates = (
        Gate(
            "filings",
            "Filings",
            (
                Check(
                    "filings.primary",
                    "Primary filing",
                    "unverified",
                    "—",
                    "filed text",
                    "No filing evidence available",
                ),
            ),
            "Unverified",
        ),
    )
    return Dossier("NVDA", "unknown", gates, (), (), (("test", "fixture", "now"),), 0.0)


def test_plain_page_view_does_not_build_a_dossier(monkeypatch: Any) -> None:
    store, key = _seed_overview()
    builder = Mock(side_effect=AssertionError("dossier built on page view"))
    monkeypatch.setattr("stonks.report_view.dossier.build_dossier", builder)
    try:
        at = _open_detail()
        assert not at.exception
        assert not any("Deep dive —" in str(md.value) for md in at.markdown)
        builder.assert_not_called()
    finally:
        store.cache_delete(key)


def test_generated_page_shows_the_gate_strip_before_the_ai_report(
    monkeypatch: Any,
) -> None:
    store, key = _seed_overview()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    factory = Mock(return_value=("PROMPT-DOSSIER-ORDER", _dossier()))
    monkeypatch.setattr("stonks.report_view.symbol_report_prompt_parts", factory)
    monkeypatch.setattr(
        "stonks.report.request_report", lambda *_a, **_k: "## TL;DR\nAnswer"
    )
    try:
        at = _open_detail()
        _generate_button(at).click().run()
        assert not at.exception
        values = [str(md.value) for md in at.markdown]
        strip = next(i for i, value in enumerate(values) if "Deep dive — NVDA" in value)
        reply = next(i for i, value in enumerate(values) if "## TL;DR" in value)
        assert strip < reply
        factory.assert_called_once()
    finally:
        store.cache_delete(key)
