# Gaps and Deferred Minors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining deferred minor and make incremental, testable progress on the four investment-decision-engine gaps: qualitative moat/reality, forward catalysts vs backward metrics, primary filing depth, and Stage 3 decision support.

**Architecture:** Extend the existing deterministic core. Dossier gates remain pure/fail-closed; provider and filing I/O stays behind `worker.py`/`filing_evidence.py`/provider modules; Streamlit renders stored/computed state. New signals should be deterministic where possible, citation-backed when derived from filings, and explicitly `unverified` when missing. No moat/catalyst/filing claim is invented by the LLM.

**Tech Stack:** Python 3.12, Streamlit, SQLite (`SQLiteStore`), pytest, `ruff`, Docker Compose, existing EDGAR/StockAnalysis/HedgeFollow/Portfolio Visualizer providers.

**Context:** PR #4 merged Phase A/B deep-dive foundation and post-review hardening. Current sanity checks are provider-compatible and green when a fresh report exists; `Checks pending` indicates missing/stale sanity report, not provider format breakage.

## Global Constraints

- Deterministic before narrative: Python computes checks/verdicts; LLM only narrates cited evidence.
- Tri-state/fail-closed: missing input is `unverified`, never `pass`.
- No provider lock-in surprises: StockAnalysis/HedgeFollow/EDGAR/PV integrations keep existing contracts; add tolerance/tests before changing parsing.
- No network in plain symbol-page render path; filing/provider fetches remain lazy/worker-driven.
- Every new check gets a stable ID, threshold/value/evidence, and tests.
- Buy-opportunity alerts must not spam: dedupe by symbol/kind/time bucket and cap banner/toast volume.
- Do not claim "complete investment decision engine" until Stage 3 gaps are addressed.

## Deferred Minors

| Minor | Status | Plan |
|---|---|---|
| Masthead AppTest flake | Mitigated | Root-cause and deflake by seeding deterministic store/sanity state or isolating Streamlit cache/session behavior in AppTest. |
| Informational filing checks permanently `unverified` | Intentional by spec | No code change unless spec changes. Keep "phrase search is evidence, not proof" and "absence of a phrase is not proof". |
| Buy-opportunity alerts not persisted | Follow-up | Add worker-generated `buy_opportunity` alert kind with weekly dedupe and retention; keep banner as current-snapshot view. |

## Gap Workstreams

### Workstream 1 — Qualitative moat / reality (deterministic proxies)

**Objective:** Improve moat/reality evidence without hallucinated narrative.

- [ ] **Task 1.1: Add moat-proxy quality checks**
  - Files: `src/stonks/dossier.py`, `tests/test_dossier.py`
  - Add stable checks such as `quality.gross_margin_level`, `quality.roic_persistence`, `quality.fcf_stability`, `quality.reinvestment_signal` only where data exists.
  - Use `unverified` when history/peer data is missing. Keep thresholds named constants.
  - Run: `.venv/bin/pytest tests/test_dossier.py -q`

- [ ] **Task 1.2: Surface moat proxy evidence in reports**
  - Files: `src/stonks/report.py`, `tests/test_symbol_report.py`
  - Require the AI memo to cite moat-proxy check IDs and explicitly state when moat is not proven.
  - Run: `.venv/bin/pytest tests/test_symbol_report.py -q`

- [ ] **Task 1.3: Add filing concentration/competition phrase evidence**
  - Files: `src/stonks/dossier.py`, `src/stonks/filing_evidence.py`, `tests/test_dossier.py`, `tests/test_edgar.py`
  - Consider high-signal informational phrases: `customer concentration` already exists; evaluate `supplier concentration`, `competition`, `pricing pressure` carefully to avoid noisy false confidence. All remain `unverified` evidence.

### Workstream 2 — Forward catalysts vs backward metrics

**Objective:** Make forward gate more forward-looking while staying deterministic.

- [ ] **Task 2.1: Quarterly acceleration/inflection checks**
  - Files: `src/stonks/dossier.py`, `tests/test_dossier.py`
  - Add checks from quarterly statements when available: `forward.revenue_acceleration`, `forward.eps_acceleration` or `forward.operating_margin_inflection`. Missing quarters => `unverified`.

- [ ] **Task 2.2: Guidance freshness and event coverage**
  - Files: `src/stonks/dossier.py`, `src/stonks/filing_evidence.py`, `tests/test_dossier.py`
  - Distinguish stale vs recent guidance; keep guidance as evidence, not proof. Add next-earnings/event-risk clarity in dossier/report.

- [ ] **Task 2.3: Persist buy-opportunity alerts**
  - Files: `src/stonks/alerts.py`, `src/stonks/worker.py`, `src/stonks/store.py`, `src/stonks/app.py`, `tests/test_alerts.py`, `tests/test_worker.py`
  - Add worker-generated `buy_opportunity` alerts for strong candidates (near 52w low and below both DCF & Lynch, or configurable threshold). Dedupe weekly; cap per sync; surface in existing alerts banner/toast.
  - Run: `.venv/bin/pytest tests/test_alerts.py tests/test_worker.py -q`

### Workstream 3 — Primary filing depth

**Objective:** Move from phrase/evidence presence to richer primary-filing review.

- [ ] **Task 3.1: Expand high-signal filing phrases and forms**
  - Files: `src/stonks/dossier.py`, `src/stonks/filing_evidence.py`, `tests/test_dossier.py`, `tests/test_edgar.py`
  - Evaluate adding phrases: `impairment`, `cybersecurity incident`, `internal control`, `covenant waiver`, `restatement of`. Consider 8-K coverage for event phrases with careful date scoping to avoid stale noise.

- [ ] **Task 3.2: Extract and cite filing snippets**
  - Files: `src/stonks/filing_evidence.py`, `src/stonks/dossier.py`, `src/stonks/report.py`, `tests/test_edgar.py`, `tests/test_symbol_report.py`
  - Store short, accession-linked snippet excerpts for hits. Never present snippet absence as clean. Include accession, filing date, form, URL.

- [ ] **Task 3.3: Add XBRL depth checks**
  - Files: `src/stonks/edgar_parse.py`, `tests/test_edgar.py`
  - Add checks where reliable: SBC, lease obligations/current debt, shares dilution from facts, current portion of debt, gross profit/operating cash flow consistency. Missing facts => `unverified`.

- [ ] **Task 3.4: Section extraction / diffing (large)**
  - Files: new parser module(s), `tests/fixtures/edgar/*`
  - Targeted extraction for 10-K/10-Q Item 1A/7/8-K event text; period-over-period diffs. Treat as separate subproject with fixtures and strict failure behavior.

### Workstream 4 — Stage 3 decision support

**Objective:** Make outputs more decision-relevant without pretending to be a full portfolio manager.

- [ ] **Task 4.1: Decision summary card**
  - Files: `src/stonks/deepdive_view.py`, `src/stonks/dossier.py`, `tests/test_deepdive_ui.py`
  - Show "what would change my mind" / key unknowns / evidence coverage / freshness prominently. No buy/sell automation.

- [ ] **Task 4.2: Portfolio fit and concentration warnings**
  - Files: `src/stonks/store.py`, `src/stonks/app.py`, `src/stonks/dossier.py`, tests
  - Add simple concentration/exposure checks from user portfolio/watchlist data. Missing portfolio data => `not_applicable`/`unverified` as appropriate.

- [ ] **Task 4.3: Position sizing/risk guardrails (scoped)**
  - Files: new `src/stonks/position_sizing.py`, UI/report integration, tests
  - Provide simple, user-configurable sizing scenarios (e.g., max % portfolio, volatility-adjusted suggestion). Clearly label as risk guardrails, not advice.

- [ ] **Task 4.4: Monitoring lifecycle**
  - Files: `src/stonks/alerts.py`, `src/stonks/worker.py`, `src/stonks/app.py`, tests
  - Add alert lifecycle states (new/seen/snoozed/resolved), thresholds, and buy-opportunity persistence. Keep dedupe and retention explicit.

## Deferred Minor Execution

- [ ] **Task M.1: Deflake masthead AppTest**
  - Files: `tests/test_followup_hardening.py`, `tests/test_app_header.py`, possibly `tests/conftest.py`
  - Seed deterministic metadata/sanity report or isolate AppTest DB state. Run repeatedly: `.venv/bin/pytest tests/test_followup_hardening.py tests/test_app_header.py -q --count=20` (if pytest-repeat available) or loop.
  - Accept when 20 consecutive runs pass locally.

## Verification Checklist

- [ ] `.venv/bin/pytest -q`
- [ ] `.venv/bin/ruff check src/ tests/`
- [ ] `.venv/bin/ruff format --check src/ tests/`
- [ ] `docker compose build`
- [ ] `docker compose config -q`
- [ ] Fresh sanity run reports all providers green or explicitly `unverified` with reason; no silent pass.
- [ ] No new network calls in plain symbol-page render path.

## Suggested Delivery Order

1. Task M.1 and Workstream 2.3 (low-risk, user-visible).
2. Workstream 1.1-1.2 (deterministic moat proxies).
3. Workstream 3.1 and 3.3 (filing depth with deterministic checks).
4. Workstream 2.1-2.2 (forward inflection).
5. Workstream 4.1-4.2 (decision support).
6. Workstream 3.4 and 4.3-4.4 (large subprojects, separate PRs if needed).

## Non-goals

- No autonomous buy/sell execution.
- No hallucinated moat/catalyst/filing claims.
- No dependency on paid/private filing APIs.
- No claim of complete investment decision engine until Stage 3 acceptance criteria are met.
