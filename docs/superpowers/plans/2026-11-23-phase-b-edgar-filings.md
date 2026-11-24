# Phase B — Primary Filing Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Phase A's placeholder `filings` gate with real, citation-backed SEC EDGAR/XBRL and full-text-search evidence, and feed it into the existing dossier, memo prompt, and UI without making any plain symbol-page view call SEC.

**Architecture:** Pure deterministic modules compute the verdict. `edgar.py` owns all HTTP, caching, rate limiting and credential validation; `edgar_parse.py` turns recorded JSON facts into `Check` objects; `dossier.py` derives the gate verdict. `report_view.py` builds evidence only on the report-generation path, which is already lazy. Nothing in `dossier.py`, `edgar.py` or `edgar_parse.py` imports Streamlit or performs I/O on construction.

**Tech Stack:** Python 3.12, existing `httpx>=0.27`, `SQLiteStore.cache_get/cache_set`, pytest, frozen dataclasses in `dossier.py`.

**Spec:** `docs/superpowers/specs/2026-11-23-per-symbol-deep-dive-design.md` (on branch `docs/per-symbol-deep-dive`; read with `git show docs/per-symbol-deep-dive:docs/superpowers/specs/2026-11-23-per-symbol-deep-dive-design.md`). This plan implements its Part 3.2, Part 4 (`guidance_present`), Part 5, Part 8 ("Read these filings"), Part 10 (filing parser tests) and Part 11.

## Global Constraints

- Deterministic gates, LLM narration: Python decides every `pass`/`fail`/`unverified`; the memo only explains what the dossier already established.
- Tri-state, fail-closed: missing input is `unverified`, never `pass`; a gate fails if any check fails, else is `unverified` if any check is unverified.
- Every check has a stable id (`filings.revenue`, `filings.debt_coverage`, …) used identically in the UI and prompt.
- No vendor lock-in: only public `data.sec.gov` and `efts.sec.gov` JSON; no API key or signup.
- `User-Agent: stonks/<version> (<contact>)` comes from `EDGAR_USER_AGENT` at call time. No hardcoded fallback. Reject unset values, values with CR/LF, values over 200 characters, and values that are not `name (address)` shaped. Never store the value in a dossier, prompt, memo or cache key.
- One process-wide limiter at ≤8 requests/second (stricter than the spec's ≤10), applied to every SEC request including the ticker map.
- Cache `edgar:cik:map` for 30 days and other `edgar:{cik}:{kind}` entries for 7 days via `SQLiteStore`; no other persistence layer.
- 403, 429, timeout, unknown CIK and unparsable payloads become `unverified` with a reason; the dossier never raises.
- Phrase hits are evidence, not proof: their checks are `unverified` by construction and link to the filing. No NLP scoring of filing prose and no risk-factor section parsing.
- Non-US filers and missing XBRL stay `unverified`; no invented values.
- No new top-level page and no network in the plain symbol-page render path.

## Review Focus

- Missing or malformed `EDGAR_USER_AGENT` must produce zero SEC requests, an `unverified` gate with `"EDGAR_USER_AGENT not configured"`, and one UI hint. Pinned by `test_missing_user_agent_disables_edgar` (Task 1) and `test_plain_page_view_never_calls_edgar` / `test_missing_user_agent_hint` (Task 4).
- Amended filings, wrong units and stale facts must never become a `pass`. Pinned by `test_latest_fact_prefers_unamended_period` and `test_wrong_unit_is_ignored` (Task 2).
- EFTS changing its response shape, returning 403/429, or timing out must degrade to `unverified`, never break the report. Pinned by `test_efts_failure_is_unverified` (Task 3) and `test_edgar_failure_still_produces_a_memo` (Task 4).
- Absent maturity tags or stale 10-K/10-Q must fail the right check rather than silently pass. Pinned by `test_absent_maturity_tags_are_unverified`, `test_debt_coverage_boundary` and `test_stale_filing_fails` (Task 2 / Task 3).
- Report generation builds filing evidence exactly once; page viewing builds none. Pinned by `test_report_click_builds_evidence_once` (Task 4).

---

### Task 1: EDGAR client — CIK resolution, limiter, cache

**Files:**
- Create: `src/stonks/edgar.py`
- Create: `tests/test_edgar.py`
- Create: `tests/fixtures/edgar/company_tickers.json`

**Interfaces:**
- Consumes: `SQLiteStore.cache_get(key, *, allow_expired=False)` and `cache_set(key, value, ttl_seconds)` from `src/stonks/store.py`; `httpx` for real requests.
- Produces:
  ```python
  class EdgarUnavailable(RuntimeError): ...
  def user_agent() -> str
  def edgar_json(
      url: str, *, store: SQLiteStore, cache_key: str, ttl_seconds: int,
      fetch: Any = None,
  ) -> Any
  def resolve_cik(symbol: str, *, store: SQLiteStore, fetch: Any = None) -> str | None
  ```
  `fetch` is called as `fetch(url, headers={"User-Agent": ...}, timeout=10.0)` and returns an object with `.status_code`, `.json()` and `.text`. Default to `httpx.get`. `user_agent()` reads `os.environ["EDGAR_USER_AGENT"]` on every call; never cache it. `edgar_json` returns cached JSON when present and stores fresh JSON only after a 2xx response.

- [ ] **Step 1: Write the failing tests** in `tests/test_edgar.py`, using `tests/fixtures/edgar/company_tickers.json` with two entries, one lowercase symbol and one numeric CIK:
  ```python
  def test_resolve_cik_pads_and_is_case_insensitive(...): ...  # 320193 -> "0000320192"
  def test_unknown_ticker_returns_none(...): ...
  def test_cached_cik_avoids_a_second_fetch(...): ...
  def test_403_raises_edgar_unavailable(...): ...
  def test_efts_429_and_timeout_are_unavailable(...): ...
  def test_limiter_never_exceeds_eight_requests_per_second(monkeypatch): ...
  @pytest.mark.parametrize("value", ["", "a\nb", "x" * 201, "not-an-address"])
  def test_invalid_user_agent_is_rejected(monkeypatch, value): ...
  def test_valid_user_agent_is_read_at_call_time(monkeypatch): ...
  ```
  For the limiter test, monkeypatch the module's monotonic clock and sleep functions; assert the ninth request waits at least `1/8` seconds from the first.

- [ ] **Step 2: Run them and watch them fail** because `stonks.edgar` does not exist:
  Run: `.venv/bin/pytest tests/test_edgar.py -q`
  Expected: FAIL with `ModuleNotFoundError: No module named 'stonks.edgar'`.

- [ ] **Step 3: Implement `src/stonks/edgar.py`** with a module-level token bucket (8 tokens refilled per second, injectable clock/sleep for tests), `TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"`, and the signatures above. `resolve_cik` caches the full ticker map once, upper-cases symbols for lookup, and zero-pads to 10 digits. Translate 403/429/timeout/unparsable responses into `EdgarUnavailable`. Do not import Streamlit or `app`.

- [ ] **Step 4: Re-run the task tests and the whole suite**:
  Run: `.venv/bin/pytest tests/test_edgar.py -q && .venv/bin/pytest -q`
  Expected: all task tests pass; the suite stays green.

- [ ] **Step 5: Update `vulture_whitelist.py`** so the public EDGAR functions used only by tests/other tasks are not reported as dead, then commit:
  ```bash
  git add src/stonks/edgar.py tests/test_edgar.py tests/fixtures/edgar/company_tickers.json vulture_whitelist.py
  git commit -m "feat: add a keyless, rate-limited EDGAR client"
  ```

### Task 2: XBRL cross-check and debt maturity ladder

**Files:**
- Create: `src/stonks/edgar_parse.py`
- Modify: `tests/test_edgar.py`
- Create: `tests/fixtures/edgar/companyfacts_sample.json`

**Interfaces:**
- Consumes: `Check` from `src/stonks/dossier.py`; the companyfacts JSON shape (`facts.us-gaap` / `facts.dei`, each with `units` and entries carrying `start`, `end`, `filed`, `form`, `accn`, `val`).
- Produces:
  ```python
  def latest_fact(
      facts: Mapping[str, Any], tags: Sequence[str], unit: str
  ) -> tuple[float, str] | None
  def filing_checks(
      row: Mapping[str, Any], statements: Mapping[str, Any], facts: Mapping[str, Any]
  ) -> tuple[list[Check], list[str]]
  def maturity_ladder(facts: Mapping[str, Any]) -> list[tuple[str, float]] | None
  ```
  `latest_fact` returns `(value, accession)`. `filing_checks` returns the seven cross-checks plus `filings.debt_coverage` and conflict strings. All returned ids are exactly: `filings.revenue`, `filings.net_income`, `filings.operating_cash_flow`, `filings.capex`, `filings.shares_out`, `filings.total_debt`, `filings.cash`, `filings.debt_coverage`.

- [ ] **Step 1: Write the failing tests** in `tests/test_edgar.py` with `tests/fixtures/edgar/companyfacts_sample.json` containing multiple periods, one amended filing, one wrong-unit entry, and the six maturity tags:
  ```python
  def test_latest_fact_prefers_unamended_period(): ...  # newest non-amended 10-K/10-Q; 10-K wins ties; /A excluded
  def test_wrong_unit_is_ignored(): ...
  def test_tolerance_boundaries_pass(): ...  # exactly 1% and exactly $1,000,000
  def test_two_percent_gap_is_a_failure_with_conflict_line(): ...  # names both values + accn
  def test_missing_tag_is_unverified(): ...
  def test_absent_maturity_tags_are_unverified(): ...
  def test_debt_coverage_boundary(): ...  # 0.9 fail, 1.1 pass
  def test_maturity_ladder_sums_five_buckets(): ...
  ```
  Use these tag aliases in order: `RevenueFromContractWithCustomerExcludingAssessedTax`, then `Revenues`; `NetIncomeLoss`; `NetCashProvidedByUsedInOperatingActivities`; `PaymentsToAcquirePropertyPlantAndEquipment`; `dei:EntityCommonStockSharesOutstanding`; `LongTermDebt` + `DebtCurrent`; `CashAndCashEquivalentsAtCarryingValue`. Unit is `USD` except `shares_out` (`shares`). Vendor values come from the screener row keys `revenue`, `net_income`, `shares_out`, `cash`, `total_debt`; where a key is absent, read the matching `id`/`label` alias from `statements["income_annual"]`, `["cash_annual"]` or `["balance_annual"]`, case-insensitively. Tolerance is `max(0.01 * abs(filing_value), 1_000_000)`.

- [ ] **Step 2: Run them and watch them fail**:
  Run: `.venv/bin/pytest tests/test_edgar.py -q -k "latest_fact or unit_is_ignored or tolerance or gap or missing_tag or maturity or debt_coverage"`
  Expected: FAIL because `stonks.edgar_parse` does not exist.

- [ ] **Step 3: Implement `src/stonks/edgar_parse.py`** with pure functions only. `filing_checks` must never invent a vendor value: missing vendor or filing input yields `status="unverified"` with a human `value` such as `"no XBRL fact"`; `differs` yields `status="fail"` and a conflict string naming both values and the accession. `maturity_ladder` uses `LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths`, `...InYearTwo` … `...InYearFive`, `...AfterYearFive`, returning `None` when any required tag or its USD value is missing. `filings.debt_coverage` passes when `(cash + free_cash_flow) / next_12m >= 1`.

- [ ] **Step 4: Re-run the task tests and the whole suite**:
  Run: `.venv/bin/pytest tests/test_edgar.py -q && .venv/bin/pytest -q`
  Expected: all pass.

- [ ] **Step 5: Commit**:
  ```bash
  git add src/stonks/edgar_parse.py tests/test_edgar.py tests/fixtures/edgar/companyfacts_sample.json vulture_whitelist.py
  git commit -m "feat: cross-check vendor figures against XBRL and verify debt maturities"
  ```

### Task 3: Filing evidence gate — EFTS sweep, red flags, freshness

**Files:**
- Create: `src/stonks/filing_evidence.py` (bundles I/O results; imports `edgar`, `edgar_parse`)
- Modify: `src/stonks/dossier.py` (owns the `FilingEvidence` dataclass and the pure gate)
- Modify: `tests/test_edgar.py`, `tests/test_dossier.py`
- Create: `tests/fixtures/edgar/efts_sample.json`

**Interfaces:**
- Consumes: `resolve_cik`, `edgar_json`, `EdgarUnavailable` (Task 1); `filing_checks`, `maturity_ladder` (Task 2); `Check`, `Gate`, `gate_status` from `dossier.py`.
- Produces:
  Define `FilingEvidence` in `dossier.py` (not in `filing_evidence.py`) so the
  dossier keeps no dependency on I/O modules:

  ```python
  @dataclass(frozen=True)
  class FilingEvidence:
      cik: str | None
      facts: Mapping[str, Any]
      hits: tuple[Mapping[str, Any], ...]
      latest_10k: str | None      # ISO filing date
      latest_10q: str | None
      guidance_hits: tuple[Mapping[str, Any], ...]
      reason: str | None          # set when EDGAR/EFTS is unavailable

  def build_filing_evidence(
      symbol: str, *, store: SQLiteStore, fetch: Any = None,
  ) -> FilingEvidence
  def search_filings(
      phrase: str, cik: str, *, forms: Sequence[str], store: SQLiteStore,
      fetch: Any = None,
  ) -> list[dict[str, Any]]
  def filing_gate(row: Mapping[str, Any], statements: Mapping[str, Any],
                  evidence: FilingEvidence, *, today: object = None) -> Gate
  # FilingEvidence.empty() -> FilingEvidence with reason "No filing evidence supplied"
  ```
  Ruling (spec wins over the older plan): `filing_gate` lives in `dossier.py`, not `edgar.py`, because all gates are pure and `edgar.py` owns I/O. `FilingEvidence` also lives in `dossier.py`; `filing_evidence.py` imports it from there, so there is no cycle. `build_filing_evidence` never raises.

- [ ] **Step 1: Write the failing tests**:
  ```python
  def test_efts_hit_parsing_yields_count_date_accession_link(): ...
  def test_material_weakness_hit_fails_the_gate_and_is_a_red_flag(): ...
  def test_zero_hits_passes_with_absence_is_not_proof_note(): ...
  def test_efts_failure_is_unverified(): ...  # monkeypatch edgar_json -> EdgarUnavailable
  def test_stale_filing_fails(): ...           # 10-K 500 days old with fixed today
  def test_phrase_checks_are_unverified_with_links(): ...  # customer concentration etc.
  def test_evidence_build_without_user_agent_makes_no_requests(): ...
  ```
  Phrases for the gate sweep are `"material weakness"`, `"going concern"`, `"covenant"`, `"restatement"`, `"SEC investigation"`; each hit must carry `count`, `filing_date`, `accession` and `url`. Informational phrase checks use the Part 3.2 phrases (`customer concentration`, `litigation`, `regulatory`, `related party`, …) and are always `unverified` with the note `"phrase search is evidence, not proof"`. Freshness fails when the 10-K is older than 400 days or the 10-Q older than 120 days, using an injected `today` value in tests.

- [ ] **Step 2: Run them and watch them fail**:
  Run: `.venv/bin/pytest tests/test_edgar.py tests/test_dossier.py -q -k "efts or material_weakness or zero_hits or stale or phrase_checks or without_user_agent"`
  Expected: FAIL because the new modules/functions do not exist.

- [ ] **Step 3: Implement the three functions and `FilingEvidence`.** Fetch companyfacts from `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` via `edgar_json`, cache key `edgar:{cik}:companyfacts`, TTL 7 days. Fetch EFTS hits via `edgar_json`, cache key `edgar:{cik}:efts:{phrase}`, TTL 7 days. Capture the newest `10-K` and `10-Q` filing dates from the fact entries. When `user_agent()` raises or any request raises `EdgarUnavailable`, return an evidence object with `reason` set and empty facts/hits; `filing_gate` then emits one `filings.primary` `unverified` check with that reason. `filing_gate` uses its `today` argument for the freshness check. Red flags include the filing link and date for each hit. No Streamlit import.

- [ ] **Step 4: Re-run the task tests and the whole suite**:
  Run: `.venv/bin/pytest tests/test_edgar.py tests/test_dossier.py -q && .venv/bin/pytest -q`
  Expected: all pass.

- [ ] **Step 5: Commit**:
  ```bash
  git add src/stonks/filing_evidence.py src/stonks/dossier.py tests/test_edgar.py tests/test_dossier.py tests/fixtures/edgar/efts_sample.json vulture_whitelist.py
  git commit -m "feat: sweep filings for red flags and check their freshness"
  ```

### Task 4: Wire filing evidence into dossier, memo and UI

**Files:**
- Modify: `src/stonks/dossier.py`
- Modify: `src/stonks/report_view.py`
- Modify: `src/stonks/deepdive_view.py`
- Modify: `tests/test_symbol_report.py`, `tests/test_symbol_report_ui.py`, `tests/test_deepdive_ui.py`

**Interfaces:**
- Consumes: `FilingEvidence`, `build_filing_evidence` (Task 3); `filing_gate` (Task 3); `forward_gate(row, *, ..., guidance_hits=())` already exists in `dossier.py`.
- Produces:
  ```python
  def build_dossier(
      symbol: str, *, row=None, forecast=None, statements=None, overview=None,
      peers=None, as_of: str | None = None, today=None,
      filing_evidence: FilingEvidence | None = None,
      guidance_hits: Sequence[Mapping[str, Any]] = (),
  ) -> Dossier
  ```
  The placeholder `filings` gate is removed. `conflicts`, `red_flags` and `provenance` on the returned `Dossier` come from the evidence when present.

- [ ] **Step 1: Write the failing tests**:
  ```python
  def test_report_click_builds_evidence_once(monkeypatch): ...  # spy on build_filing_evidence
  def test_plain_page_view_never_calls_edgar(monkeypatch): ...   # AppTest, no click
  def test_edgar_failure_still_produces_a_memo(monkeypatch): ... # evidence.reason set
  def test_gate_strip_shows_real_filings_gate_and_conflicts(): ...
  def test_missing_user_agent_hint(): ...
  def test_guidance_hits_reach_the_forward_gate(): ...
  ```
  Use the existing `_Store`, `_open_detail()` and `_generate_button()` helpers in `tests/test_symbol_report.py` / `tests/test_symbol_report_ui.py`. Monkeypatch `report_view.filing_evidence.build_filing_evidence` so no test touches the network. Assert the plain page view issues zero calls, one Generate click issues exactly one, and a memo is still generated when the evidence carries `reason="EDGAR_USER_AGENT not configured"`.

- [ ] **Step 2: Run them and watch them fail**:
  Run: `.venv/bin/pytest tests/test_symbol_report.py tests/test_symbol_report_ui.py tests/test_deepdive_ui.py -q -k "evidence or edgar or filings_gate or user_agent_hint or guidance_hits"`
  Expected: FAIL because `build_dossier` has no `filing_evidence` parameter and the hint does not exist.

- [ ] **Step 3: Implement the wiring.** In `report_view.symbol_report_prompt_parts`, after the statements are parsed, call `filing_evidence.build_filing_evidence(symbol, store=store)` and pass its value and `evidence.guidance_hits` into `dossier.build_dossier`; this function is reached only from Generate/Debug, never from a plain page render. In `dossier.build_dossier`, replace the placeholder gate with `filing_gate(row, statements, filing_evidence or FilingEvidence.empty(), today=today)` and merge evidence conflicts/red flags/provenance. In `deepdive_view.render_deep_dive`, show exactly one caption — `Set EDGAR_USER_AGENT to verify filings` — when the filings gate is `unverified` with that reason; keep the existing link rendering for hits.

- [ ] **Step 4: Re-run the task tests and the whole suite**:
  Run: `.venv/bin/pytest tests/test_symbol_report.py tests/test_symbol_report_ui.py tests/test_deepdive_ui.py -q && .venv/bin/pytest -q`
  Expected: all pass.

- [ ] **Step 5: Verify lint and commit**:
  Run: `.venv/bin/ruff check src/stonks tests && .venv/bin/ruff format --check src/stonks tests && docker compose build`
  Expected: ruff clean; both images rebuild successfully.
  ```bash
  git add src/stonks/dossier.py src/stonks/report_view.py src/stonks/deepdive_view.py tests/test_symbol_report.py tests/test_symbol_report_ui.py tests/test_deepdive_ui.py vulture_whitelist.py
  git commit -m "feat: feed primary filing evidence into the deep dive"
  ```

## Notes for the implementer

- The report cache already keys on the full prompt text, and `dossier_block()` is part of that text, so new gate checks and conflicts invalidate the memo without a separate hash argument.
- Phase C (portfolio holdings, sizing, correlation, persistence) and Phase D (README/offline smoke test) are not in this plan. Do not add holdings input, a `deep_dives` table, or a new page.
- Keep the `.env` contract from Phase A: `EDGAR_USER_AGENT` is optional at the compose level, so absence must disable SEC calls rather than prevent startup.
