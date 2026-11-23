"""Deterministic evidence model for the per-symbol deep dive.

Every verdict in a deep dive is computed here, in Python, from named fields with
fixed thresholds: the model receives the checks and explains them, it never
decides them. Each check is tri-state and fail-closed — a check whose input is
missing is ``unverified``, never ``pass`` — and a gate's status is derived from
its checks rather than assigned.

The module is pure: no I/O, no Streamlit import, no network, so the same inputs
always produce the same dossier.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Status = Literal["pass", "fail", "unverified", "not_applicable"]


@dataclass(frozen=True)
class Check:
    """One auditable pass/fail question, with the numbers behind the answer."""

    id: str
    label: str
    status: Status
    value: str
    threshold: str
    evidence: str


@dataclass(frozen=True)
class Gate:
    """A group of checks that share a question, plus a one-line verdict."""

    key: str
    label: str
    checks: tuple[Check, ...]
    summary: str


@dataclass(frozen=True)
class Dossier:
    """The full evidence set for one symbol at one point in time."""

    symbol: str
    as_of: str
    gates: tuple[Gate, ...]
    conflicts: tuple[str, ...]
    red_flags: tuple[str, ...]
    provenance: tuple[tuple[str, str, str], ...]
    coverage: float


def gate_status(checks: Sequence[Check]) -> Status:
    """Derive a gate's status from its checks.

    Any failure fails the gate; otherwise anything unverifiable leaves it
    unverified. A gate whose checks all legitimately do not apply is
    ``not_applicable``, while a gate with no checks at all is ``unverified``: an
    empty gate proves nothing and must not read as a pass.
    """
    if not checks:
        return "unverified"
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "unverified" in statuses:
        return "unverified"
    if any(check.status == "pass" for check in checks):
        return "pass"
    return "not_applicable"


def coverage(gates: Iterable[Gate]) -> float:
    """Fraction of applicable checks that passed, across every gate.

    Checks that do not apply are excluded from both numerator and denominator,
    so a symbol with many inapplicable checks is neither rewarded nor punished.
    """
    applicable = [
        check
        for gate in gates
        for check in gate.checks
        if check.status != "not_applicable"
    ]
    if not applicable:
        return 0.0
    passed = sum(1 for check in applicable if check.status == "pass")
    return passed / len(applicable)
