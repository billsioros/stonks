"""The dossier is the deterministic half of the deep dive.

These tests pin the status algebra: a gate fails on any failure, is unverified
when nothing fails but something could not be checked, and passes only when
every applicable check passed. Coverage is passed/applicable, so checks that do
not apply never dilute the number.
"""

from __future__ import annotations

from stonks.dossier import Check, Dossier, Gate, coverage, gate_status


def _check(status: str, check_id: str = "q.a") -> Check:
    return Check(check_id, "A", status, "1", ">= 0", "test")  # type: ignore[arg-type]


def _gate(*checks: Check) -> Gate:
    return Gate("quality", "Quality", checks, "")


def test_gate_status_fails_on_any_failure() -> None:
    assert gate_status((_check("pass"), _check("fail"))) == "fail"


def test_gate_status_is_unverified_when_nothing_fails_but_something_is_unknown() -> (
    None
):
    assert gate_status((_check("pass"), _check("unverified"))) == "unverified"


def test_gate_status_passes_only_when_every_applicable_check_passes() -> None:
    assert gate_status((_check("pass"), _check("not_applicable"))) == "pass"


def test_gate_status_is_not_applicable_when_no_check_applies() -> None:
    assert (
        gate_status((_check("not_applicable"), _check("not_applicable")))
        == "not_applicable"
    )


def test_gate_status_of_an_empty_gate_is_unverified_not_pass() -> None:
    assert gate_status(()) == "unverified"


def test_coverage_excludes_not_applicable_checks() -> None:
    gate = _gate(_check("pass"), _check("unverified"), _check("not_applicable"))
    assert coverage((gate,)) == 0.5


def test_coverage_is_zero_when_nothing_applies() -> None:
    assert coverage((_gate(_check("not_applicable")),)) == 0.0


def test_coverage_spans_every_gate() -> None:
    first = _gate(_check("pass"))
    second = Gate("forward", "Forward", (_check("fail"),), "")
    assert coverage((first, second)) == 0.5


def test_checks_are_immutable_so_one_gate_cannot_edit_another() -> None:
    check = _check("pass")
    try:
        check.status = "fail"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Check should be frozen")


def test_dossier_carries_its_evidence_beyond_the_gates() -> None:
    dossier = Dossier(
        symbol="AAPL",
        as_of="2026-11-23T09:00:00Z",
        gates=(_gate(_check("pass")),),
        conflicts=("revenue differs: 1.0 vs 1.2 (0000320193-25-000001)",),
        red_flags=("material weakness (2025-10-30)",),
        provenance=(("screener", "row snapshot", "1h"),),
        coverage=1.0,
    )
    assert dossier.symbol == "AAPL"
    assert dossier.conflicts and dossier.red_flags
    assert dossier.provenance[0][0] == "screener"
