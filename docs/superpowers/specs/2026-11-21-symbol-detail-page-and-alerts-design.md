# Symbol Detail Page & In-App Alerts — Design

## Intent

Make a screener row lead somewhere useful: clicking a symbol opens an in-app page modelled on
stockanalysis.com (`overview`, `financials`, `statistics`, `metrics`, `forecast`) so a buying
decision can be made without leaving the app. Then surface "something interesting happened" for
watchlist symbols as in-app banners and badges, the way roomies does it.

Two phases, shipped separately:

- **A — Symbol detail page.** Read-only per-symbol view over the same StockAnalysis host the bulk
  sync already uses.
- **B — Alerts and news.** Worker-computed alerts from screener columns plus Yahoo Finance news
  headlines for watchlist symbols, rendered as banners/badges in the screener.

## Goals

- Any symbol in the screener table or watchlist opens a detail page in-app, with a way back.
- Detail page has the five tabs the user named, and the Financials tab mirrors the real page:
  four statements × annual/quarterly, TTM column, growth rows, full available history.
- Per-symbol data is fetched fresh on open and cached; a stale/failed fetch never breaks the page.
- Alerts fire on meaningful change for watched symbols only, deduped so nothing repeats every sync.
- Watchlist headlines from Yahoo Finance reach the user as alerts and on the Overview block.

## Non-goals

- No `yfinance` dependency and no Yahoo fundamentals path; the Yahoo route remains news-only.
- No email, push, desktop notification, webhook, or notification inbox outside the app.
- No alert rule editor UI, no per-user thresholds in phase B (thresholds are module constants).
- No background pre-fetch of detail pages for non-watchlist symbols.
- No schema changes to `stocks` beyond what already exists; no change to `get_stocks` signature.

## Constraints

- Missing provider data stays `NULL`/`—`. Never synthesise a value, never carry a value across
  periods, never show a placeholder as if it were data.
- Use `uv run` for every Python command; `uv run pytest -q` and `uv run ruff check src tests` pass.
- `uv.lock` has a pre-existing unrelated modification and is never staged or committed.
- Existing visual language only: flat dark cards, indigo accent `#6366f1`, `section-header`,
  `.sk-*` classes, `[class*="st-key-..."]` containers, 44px rows.
- Work stays on `feature/yahoo-migration-minors`.

## Data sources (verified 2026-11-21)

All StockAnalysis routes are on the host already in `stockanalysis.py`, fetched with the existing
`User-Agent: Mozilla/5.0 (compatible; stonks)` and the existing 3-attempt/60s-timeout `fetch_json`.

| Purpose | Route |
| --- | --- |
| Quote header, profile, overview stats, **headlines** | `/stocks/{sym}/__data.json` |
| Statistics tab | `/stocks/{sym}/statistics/__data.json` |
| Financials (any statement, either period) | `/stocks/{sym}/financials/{statement}/__data.json[?p=quarterly]` |
| Forecast tab | `/stocks/{sym}/forecast/__data.json` |

`{statement}` ∈ `income-statement`, `balance-sheet`, `cash-flow-statement`, `ratios`.
There is **no** dedicated news route (`/stocks/{sym}/news/__data.json` and `/overview/__data.json`
both 404), but the overview payload ships the headlines inline at `news.data`:
`{url, title, text, source, time, ago, img, type}`. Overview therefore carries its own news block
for free — no extra request, no second provider.

Yahoo's RSS headline feed is kept on record as the fallback if StockAnalysis coverage proves thin:
`https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US` returns ~20 fresh
symbol-scoped items (verified working 2026-11-21, `s=NVDA,AMD` silently returns only NVDA). It is
**not** wired up in this design.

### Payload resolution

SvelteKit/devalue format: `{"type":"data","nodes":[...]}`, page data at `nodes[2].data`. The
payload holds one flat array; **values in that array are literals**, while integer fields inside
dicts/lists are indices into the same array. Resolution rules:

- `i < 0` or `i >= len(array)` → `None`.
- Integers found inside the array itself are literals and must **not** be dereferenced again.
- Memoise by index and guard cycles; a naive recursive resolver takes minutes.

The resolver lives in a new `src/stonks/detail.py` (or `stockanalysis_detail.py` if `detail.py`
grows past parsing) next to the fetch layer, and is unit-tested against a recorded payload.

### Statement shape

`financialData` is column-oriented: `datekey` first, then line items (`revenue`, `gp`,
`netinccmn`, …). Annual `datekey` starts with `TTM` then fiscal years; quarterly holds ~16
quarters. `sections[].rows[]` supplies row id/title and display order; `map` supplies per-row
metadata (title, format, unit) so numbers format the way the site formats them. `prior`,
`ttmPrior` and `ttmGrowth` provide the growth rows.

## Phase A — Detail page

### Navigation

`st.session_state.page` ∈ `{"screener", "detail"}` with `st.session_state.detail_symbol`. The
screener table gets `on_select="rerun"` with `selection_mode="single-row"`; a selected row sets
`page="detail"` and the symbol. The detail page renders a `← Back to screener` control that
restores the previous filters, preset and page. Watchlist rows open the same page.

Deep links are not required; state is in-session only.

### Tabs

- **Overview** — quote header (price and 52-week range from the store row, market cap, exchange,
  sector/industry from the page payload), a **signal strip** of the stored screener metrics
  (analyst rating, target upside, DCF/Lynch upside, short %, position in the 52-week range) shown
  as plain labelled values — no composite score is invented — then the **news block**: latest 5
  headlines from the payload's `news.data` with source and relative age, each an external link.
- **Financials** — sub-tabs Income Statement / Balance Sheet / Cash Flow / Ratios, each with an
  Annual ⇄ Quarterly switch, period columns with a TTM column where the payload provides one,
  growth rows, and a sticky first column of row labels.
- **Statistics** — valuation, financial position, financial efficiency, dividends, short interest,
  share statistics.
- **Metrics** — margins, returns, EV ratios, per-share figures, and the site's own scores.
- **Forecast** — price targets (low/median/average/high, count, updated date), this/next-year
  revenue and EPS estimates, recommendation mix, and recent analyst actions.

Every section renders only fields the payload actually contains. A missing section renders
nothing; a missing value renders `—`.

### Caching

Reuse `kv_cache` (table already exists, currently has no accessors). Add to `SQLiteStore`:

- `cache_set(key, value, ttl_seconds)` / `cache_get(key)` returning `None` when absent or expired.

Keys: `sym:{SYMBOL}:{page}:{period}` for StockAnalysis payloads.

TTL: 900s for `overview`/`statistics`/`forecast`, 86400s for `financials`. News rides in the
overview payload, so it inherits the 900s TTL.

Each payload section shows an "as of HH:MM" stamp plus a refresh control that bypasses the cache
for that page. A cache hit still renders instantly; a failed fetch with a cache hit falls back to
the cached copy and marks it stale.

## Phase B — Alerts and news

### Storage

```sql
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,      -- info | good | warn
    title TEXT NOT NULL,
    detail TEXT,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    seen_at REAL
)
```

`dedupe_key` is `{symbol}:{kind}:{bucket}`, where the bucket is the ISO week for threshold rules
and the article link for news. An `INSERT OR IGNORE` on that unique key gives idempotent syncs.

Store API: `add_alert(...) -> bool`, `get_alerts(unread_only, limit)`, `get_alerts_for_symbol()`,
`mark_alerts_seen(ids)`, `count_unread_alerts()`.

### Worker flow

`job()` today fetches rows then calls `replace_stocks`, which deletes every row. The diff therefore
has to happen in this order:

1. `previous = store.get_stocks(filters={"symbol": {"values": watchlist}}, page_size=len)` — the
   pre-sync snapshot of watched symbols.
2. Fetch the new screener rows (unchanged path) and the HedgeFollow flags.
3. `store.replace_stocks(rows)` and `save_metadata(...)` as today.
4. For each watched symbol present in both snapshots, evaluate the rules and `add_alert(...)`.
5. For each watched symbol, fetch the overview payload, cache it, and add a `news` alert for
   `news.data` links not yet present in `alerts`.

Any failure in step 4/5 is logged and skipped; the sync itself still succeeds. No alerts are
emitted for symbols newly added to the watchlist (no previous snapshot) except news.

### Rules (screener columns only)

Module constants in one place, with a short human string per rule:

| kind | condition | severity |
| --- | --- | --- |
| `off_high` | `price <= 0.80 * week_52_high`, previously true | good |
| `near_low` | `price <= 1.05 * week_52_low`, previously false | good |
| `pe_drop` | `pe_ratio` down ≥15% vs previous, both non-null | good |
| `fair_value` | `dcf_upside_pct >= 25` or `lynch_upside_pct >= 25`, previously false | good |
| `target_upside` | `pt_upside_pct >= 25` and `rating` present, previously false | good |
| `short_rise` | `short_pct` up ≥2.0 points vs previous | warn |
| `big_move` | `abs(price / previous_price - 1) >= 0.05` | warn |
| `hedge_fund` | `hedge_fund_buys` 0 → 1 | good |
| `news` | headline link in `news.data` not seen before | info |

Thresholds are deliberately conservative; a rule needs both a previous and a current value unless
its condition is absolute. No alert is emitted when either side is `NULL`.

### UI

- **Banner** — at the top of the screener tab, `st.info(..., icon="🔔")` inside a keyed container,
  summarising unread alerts as one line each: severity dot, symbol (clickable → detail page), and
  the alert text. Renders nothing when there are none, exactly like roomies.
- **Watchlist badge** — the Watchlist tab label gains `(n)` while any unread alert exists for a
  watched symbol; the watchlist table gains a marker column so the row with news is obvious.
- **Mark read** — a `Mark all read` button clears `seen_at` for everything shown; alerts older
  than 14 days are pruned on worker start.

Alerts are computed by the worker, so the banner reflects the last sync. If the worker has never
run, the banner simply shows nothing.

## Failure modes

| Situation | Behaviour |
| --- | --- |
| Per-symbol fetch fails, cache warm | render cached copy, marked stale |
| Per-symbol fetch fails, cache cold | error card + retry, no partial tab |
| Symbol has no StockAnalysis page (delisted/foreign) | "No data for SYMBOL", back control |
| Payload shape changes | resolver returns `None` for unknown indices; sections render `—` |
| Overview fetch unreachable | news block and news alerts skipped, logged once |
| Worker not running | banner empty; detail page still works from live fetches |

## Verification

- `uv run pytest -q` — new unit tests for the devalue resolver (literals vs indices, negative and
  out-of-range indices, cycles), each parser against recorded payloads, cache TTL expiry, each
  alert rule (fires / does not fire / NULL side), and dedupe idempotency.
- `uv run ruff check src tests` and `uv run ruff format --check src tests`.
- AppTest smoke run: screener renders, detail page opens for a stubbed symbol, alerts banner
  renders with a seeded alert and disappears after "Mark all read".
- One live end-to-end check against NVDA for each tab, plus a worker run confirming alerts land in
  the table.

## Rollout

Phase A first as its own change set, then Phase B. Both land on
`feature/yahoo-migration-minors`; no push, no deploy.
