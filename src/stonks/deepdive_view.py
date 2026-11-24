"""Streamlit panels for the deterministic per-symbol deep dive.

Everything shown here is read from the dossier. The view never recomputes a
status, compares a number to a threshold or decides that missing input is a
pass: those judgements belong to ``dossier.py`` and must read identically in
the memo and on the page.
"""

from __future__ import annotations

import re
from typing import Any

import streamlit as st

from stonks.dossier import Dossier, gate_status
from stonks.edgar import USER_AGENT_REASON

GLYPHS = {
    "pass": "✅",
    "fail": "⛔",
    "unverified": "❔",
    "not_applicable": "➖",
}
_SEVERITY = {"fail": 0, "unverified": 1, "not_applicable": 2, "pass": 3}
USER_AGENT_HINT = "Set EDGAR_USER_AGENT to verify filings"

__all__ = [
    "render_check_tables",
    "render_deep_dive",
    "render_filings",
    "render_gate_strip",
    "render_portfolio_panel",
]


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_gate_strip(dossier: Dossier) -> None:
    """One badge per gate, with coverage alongside rather than implicit in green."""
    badges = " · ".join(
        f"{GLYPHS[gate_status(gate.checks)]} {gate.label}" for gate in dossier.gates
    )
    st.markdown(f"{badges} · Coverage: {dossier.coverage:.0%}")
    st.caption(f"As of {dossier.as_of}")


def render_check_tables(dossier: Dossier) -> None:
    """The checks behind each verdict, with the problems first."""
    for gate in dossier.gates:
        status = gate_status(gate.checks)
        with st.expander(f"{GLYPHS[status]} {gate.label}", expanded=status == "fail"):
            st.caption(gate.summary)
            ordered = sorted(gate.checks, key=lambda check: _SEVERITY[check.status])
            st.markdown(
                _table(
                    ("id", "check", "status", "value", "threshold", "evidence"),
                    [
                        (
                            check.id,
                            check.label,
                            check.status,
                            check.value,
                            check.threshold,
                            check.evidence,
                        )
                        for check in ordered
                    ],
                )
            )


def render_filings(dossier: Dossier) -> None:
    """Dated red-flag and cross-check hits, linked straight to the filing."""
    lines = ["### Read these filings"]
    for item in (*dossier.red_flags, *dossier.conflicts):
        match = re.search(r"https?://\S+", item)
        if match:
            url = match.group(0)
            label = item.replace(url, "").strip(" —-")
            lines.append(f"- {label} — [filing]({url})")
        elif item:
            lines.append(f"- {item}")
    if len(lines) == 1:
        lines.append("- No filings were read for this dossier.")
    st.markdown("\n".join(lines))


def _needs_user_agent_hint(dossier: Dossier) -> bool:
    """True only when the filings primary check names the contact-string problem."""
    filings = next((gate for gate in dossier.gates if gate.key == "filings"), None)
    if filings is None or gate_status(filings.checks) != "unverified":
        return False
    primary = next(
        (check for check in filings.checks if check.id == "filings.primary"), None
    )
    return (
        primary is not None
        and primary.status == "unverified"
        and primary.value == USER_AGENT_REASON
    )


def render_portfolio_panel(store: Any, dossier: Dossier) -> None:
    """Portfolio fit checks and sizing ceiling, with no portfolio as a dash."""
    fit = next((gate for gate in dossier.gates if gate.key == "fit"), None)
    with st.expander("Portfolio fit"):
        if fit is None or all(check.status == "not_applicable" for check in fit.checks):
            st.caption("No portfolio supplied — fit checks do not apply.")
            return
        st.caption(fit.summary)
        st.markdown(
            _table(
                ("id", "check", "status", "value", "threshold"),
                [
                    (
                        check.id,
                        check.label,
                        check.status,
                        check.value,
                        check.threshold,
                    )
                    for check in fit.checks
                ],
            )
        )


def render_deep_dive(store: Any, symbol: str, dossier: Dossier) -> None:
    """Render the whole dossier above the symbol page's existing sections."""
    st.markdown(f"### Deep dive — {symbol}")
    render_gate_strip(dossier)
    if _needs_user_agent_hint(dossier):
        st.caption(USER_AGENT_HINT)
    render_check_tables(dossier)
    render_filings(dossier)
    render_portfolio_panel(store, dossier)
    st.caption(
        "Provenance: "
        + ", ".join(f"{source} ({age})" for source, _, age in dossier.provenance)
    )
