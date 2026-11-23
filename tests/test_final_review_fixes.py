"""Regression tests from the whole-branch review of Phase A."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from stonks import app, dossier, report_view
from stonks.dossier import Gate


def test_report_bundle_uses_the_keys_the_gates_read(monkeypatch: Any) -> None:
    """Provider statement names must not leave five gate checks unverified."""
    captured: dict[str, Any] = {}

    class Store:
        def get_stocks(self, **kwargs: Any) -> tuple[list[dict[str, Any]], int, int]:
            return [], 0, 0

    def fake_load_page(
        store: Any, symbol: str, page: str, **kwargs: Any
    ) -> tuple[Any, float]:
        return {"raw": page}, 1.0

    def fake_build(symbol: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return dossier.Dossier(
            symbol=symbol,
            as_of="unknown",
            gates=(),
            conflicts=(),
            red_flags=(),
            provenance=(),
            coverage=0.0,
        )

    monkeypatch.setattr(report_view.detail, "load_page", fake_load_page)
    monkeypatch.setattr(report_view.detail, "load_history", lambda *a, **k: [])
    monkeypatch.setattr(report_view.dossier, "build_dossier", fake_build)
    report_view.symbol_report_prompt_parts(Store(), "NVDA")
    statements = captured["statements"]
    assert "income_annual" in statements
    assert "balance_annual" in statements
    assert "income_quarterly" in statements


def test_build_dossier_feeds_industry_medians_from_the_stored_universe() -> None:
    rows = [
        {
            "symbol": f"S{i}",
            "industry": "Semiconductors",
            "operating_margin_pct": 30.0 + i,
            "revenue_growth_5y_pct": 20.0 + i,
        }
        for i in range(6)
    ]
    built = dossier.build_dossier("S0", row=rows[0], peers=rows)
    checks = {check.id: check for gate in built.gates for check in gate.checks}
    assert "fewer than five peers" not in checks["quality.margin_vs_industry"].value
    assert checks["quality.margin_vs_industry"].status == "fail"


def test_provider_earnings_date_is_parsed() -> None:
    assert dossier._as_date("Nov 17, 2026") == date(2026, 11, 17)


def test_missing_buyback_history_cannot_make_a_payout_pass() -> None:
    statement = {
        "periods": [{"is_ttm": False}] * 3,
        "rows": [
            {"id": "dps", "values": [1.0, 1.0, 1.0]},
            {"id": "sharesDiluted", "values": [100.0, 100.0, 100.0]},
            {"id": "treasuryStock", "values": [None, None, None]},
        ],
    }
    gate = dossier.quality_gate(
        {"free_cash_flow": 1_000.0},
        statements={"income_annual": statement, "balance_annual": statement},
    )
    check = next(c for c in gate.checks if c.id == "quality.shareholder_yield")
    assert check.status == "unverified"


def test_as_of_and_today_are_passed_through_the_dossier(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    real_forward = dossier.forward_gate

    def capture(row: Any, **kwargs: Any) -> Gate:
        captured.update(kwargs)
        return real_forward(row, **kwargs)

    monkeypatch.setattr(dossier, "forward_gate", capture)
    built = dossier.build_dossier(
        "NVDA", as_of="2026-11-23T12:00:00Z", today=date(2026, 11, 23)
    )
    assert built.as_of == "2026-11-23T12:00:00Z"
    assert captured["today"] == date(2026, 11, 23)


def test_failed_first_sync_is_red_and_bad_metadata_is_tolerated() -> None:
    assert app.live_sync_state({"last_sync_status": "failed"}).level == "fail"
    assert (
        app.live_sync_state({"last_successful_sync_at": "not-a-time"}).level
        == "unknown"
    )


def test_environment_file_is_optional_for_a_fresh_clone() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("required: false") >= 2
