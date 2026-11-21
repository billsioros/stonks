# In-App Alerts & News Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The worker notices meaningful changes for watchlist symbols — cheapness thresholds, analyst target moves, short-interest jumps, fresh headlines — and the app surfaces them as a roomies-style banner, a tab badge and a marker column, with nothing stored outside the app.

**Architecture:** A pure rules module turns two screener snapshots into `Alert` records; the worker writes them through a new `alerts` table with a URL/stage-based dedupe key, and also records unseen StockAnalysis headlines as `news` alerts. The screener renders unread alerts in a banner that renders nothing when empty, plus a count badge on the Watchlist tab.

**Tech Stack:** Python 3.12, Streamlit 1.56, SQLite (stdlib), pandas, `schedule`; `uv` for all commands.

**Spec:** `docs/superpowers/specs/2026-11-21-symbol-detail-page-and-alerts-design.md`, Phase B. Phase A (the detail page) is already implemented on this branch.

## Global Constraints

- Missing values stay `None`; a rule never fires when either side of its comparison is `NULL`.
- Alerts are computed only by the worker (`stonks.worker.job`), never at page render.
- Every alert insert is idempotent: the same `dedupe_key` never inserts twice.
- No email, push, desktop notification or webhook; nothing leaves the app.
- Use `uv run` for every Python command; `uv run pytest -q` and `uv run ruff check src tests` must pass.
- `uv.lock` is never staged or committed. Work stays on `feature/yahoo-migration-minors`; no push.
- Existing look only: indigo `#6366f1`, `.sk-*` classes, `section-header`, the `st.info(..., icon="🔔")` banner idiom.
- Alert thresholds are module constants, not user-editable settings.

## Review Focus

1. A watchlist symbol that is brand new (no previous snapshot) — must produce no price/P-E alerts and exactly the news alerts, not a burst of "changed" alerts from `None` baselines.
2. A symbol whose provider value flips from `NULL` to a number (or back) — the comparison must be skipped, not treated as a 100% move.
3. Two consecutive worker runs with unchanged data — the second must insert zero alerts (dedupe holds) and the banner must not grow.
4. A worker run with an empty watchlist — must complete the sync normally and write no alerts, without errors.
5. The banner with everything marked read — must render nothing at all (no empty info box), exactly like roomies.

---

### Task 1: Alerts table and store API

**Files:**
- Modify: `src/stonks/store.py` (`_init_db` ~line 88-220, then new `# ── Alerts ──` section after `cache_delete`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: existing `self._connect()`, `time.time()`.
- Produces:
  - `add_alert(self, symbol: str, kind: str, severity: str, title: str, detail: str | None, dedupe_key: str) -> bool` — `True` when a row was inserted.
  - `get_alerts(self, *, unread_only: bool = True, symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]` — newest first, keys `id, symbol, kind, severity, title, detail, dedupe_key, created_at, seen_at`.
  - `mark_alerts_seen(self, ids: list[int]) -> None`
  - `count_unread_alerts(self) -> int`
  - `prune_alerts(self, older_than_days: int = 14) -> int` — returns rows deleted.

- [ ] **Step 1: Write the failing tests**

```python
def test_add_alert_is_idempotent(store):
    assert store.add_alert("NVDA", "pe_drop", "good", "P/E down 20%", None, "NVDA:pe_drop:2026-W47") is True
    assert store.add_alert("NVDA", "pe_drop", "good", "P/E down 20%", None, "NVDA:pe_drop:2026-W47") is False
    assert len(store.get_alerts()) == 1

def test_get_alerts_unread_only_and_newest_first(store):
    store.add_alert("AAA", "big_move", "warn", "moved", None, "AAA:big_move:1")
    store.add_alert("BBB", "off_high", "good", "cheap", None, "BBB:off_high:1")
    alerts = store.get_alerts()
    assert [a["symbol"] for a in alerts] == ["BBB", "AAA"]
    store.mark_alerts_seen([alerts[0]["id"]])
    assert [a["symbol"] for a in store.get_alerts()] == ["AAA"]
    assert len(store.get_alerts(unread_only=False)) == 2

def test_get_alerts_filters_by_symbol(store):
    store.add_alert("AAA", "off_high", "good", "cheap", None, "AAA:off_high:1")
    store.add_alert("BBB", "off_high", "good", "cheap", None, "BBB:off_high:1")
    assert [a["symbol"] for a in store.get_alerts(symbol="AAA")] == ["AAA"]

def test_count_unread_and_mark_read(store):
    store.add_alert("AAA", "off_high", "good", "cheap", None, "AAA:off_high:1")
    store.add_alert("BBB", "off_high", "good", "cheap", None, "BBB:off_high:1")
    assert store.count_unread_alerts() == 2
    store.mark_alerts_seen([a["id"] for a in store.get_alerts()])
    assert store.count_unread_alerts() == 0

def test_prune_alerts_drops_old_rows(store):
    store.add_alert("OLD", "off_high", "good", "cheap", None, "OLD:off_high:1")
    with store._connect() as conn:
        conn.execute("UPDATE alerts SET created_at = ?", (time.time() - 30 * 86400,))
        conn.commit()
    store.add_alert("NEW", "off_high", "good", "cheap", None, "NEW:off_high:1")
    assert store.prune_alerts(14) == 1
    assert [a["symbol"] for a in store.get_alerts(unread_only=False)] == ["NEW"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store.py -k alert -v`
Expected: FAIL — `SQLiteStore` has no attribute `add_alert`.

- [ ] **Step 3: Implement**

Create the table in `_init_db` exactly as the spec's schema (`dedupe_key TEXT NOT NULL UNIQUE`). `add_alert` uses `INSERT OR IGNORE` and returns `cursor.rowcount > 0`. `get_alerts` orders by `created_at DESC, id DESC` and applies `seen_at IS NULL` when `unread_only`. `mark_alerts_seen` sets `seen_at = time.time()` for the given ids, ignoring an empty list. `prune_alerts` deletes rows older than `older_than_days` and returns `cursor.rowcount`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_store.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/store.py tests/test_store.py
git commit -m "feat(store): add alerts table and read/unread API"
```

---

### Task 2: Alert rules

**Files:**
- Create: `src/stonks/alerts.py`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure functions over plain dicts shaped like `stocks` rows).
- Produces:
  - `OFF_HIGH_RATIO = 0.80`, `NEAR_LOW_RATIO = 1.05`, `PE_DROP_RATIO = 0.85`, `VALUE_UPSIDE_PCT = 25.0`, `TARGET_UPSIDE_PCT = 25.0`, `SHORT_RISE_POINTS = 2.0`, `BIG_MOVE_RATIO = 0.05`
  - `@dataclass(frozen=True) class Alert: symbol: str; kind: str; severity: str; title: str; detail: str; dedupe_key: str`
  - `week_bucket(now: datetime | None = None) -> str` → `"2026-W47"`
  - `evaluate_alerts(previous: dict[str, Any] | None, current: dict[str, Any], *, bucket: str | None = None) -> list[Alert]`

- [ ] **Step 1: Write the failing tests**

```python
def _row(**kw):
    base = {"symbol": "AAA", "price": 100.0, "week_52_high": 200.0, "week_52_low": 90.0,
            "pe_ratio": 20.0, "dcf_upside_pct": 0.0, "lynch_upside_pct": 0.0,
            "pt_upside_pct": 0.0, "rating": "Buy", "short_pct": 1.0,
            "hedge_fund_buys": 0}
    base.update(kw)
    return base

def test_week_bucket():
    assert week_bucket(datetime(2026, 11, 21)) == "2026-W47"

def test_off_high_fires_only_on_crossing():
    crossed = evaluate_alerts(_row(), _row(price=150.0), bucket="2026-W47")
    assert [a.kind for a in crossed] == ["off_high"]
    assert crossed[0].severity == "good"
    assert crossed[0].dedupe_key == "AAA:off_high:2026-W47"
    assert evaluate_alerts(_row(price=150.0), _row(price=140.0), bucket="2026-W47") == []

def test_near_low_fires_only_on_crossing():
    assert [a.kind for a in evaluate_alerts(_row(price=100.0), _row(price=92.0), bucket="b")] == ["near_low"]

def test_pe_drop_needs_both_sides():
    assert [a.kind for a in evaluate_alerts(_row(pe_ratio=20.0), _row(pe_ratio=16.0), bucket="b")] == ["pe_drop"]
    assert evaluate_alerts(_row(pe_ratio=None), _row(pe_ratio=16.0), bucket="b") == []

def test_fair_value_and_target_upside():
    assert [a.kind for a in evaluate_alerts(_row(), _row(dcf_upside_pct=30.0), bucket="b")] == ["fair_value"]
    fired = evaluate_alerts(_row(), _row(pt_upside_pct=40.0), bucket="b")
    assert [a.kind for a in fired] == ["target_upside"]
    assert evaluate_alerts(_row(), _row(pt_upside_pct=40.0, rating=None), bucket="b") == []

def test_short_rise_and_big_move_are_warnings():
    short = evaluate_alerts(_row(short_pct=1.0), _row(short_pct=4.0), bucket="b")
    assert [(a.kind, a.severity) for a in short] == [("short_rise", "warn")]
    moved = evaluate_alerts(_row(price=100.0), _row(price=108.0), bucket="b")
    assert [(a.kind, a.severity) for a in moved] == [("big_move", "warn")]

def test_hedge_fund_flag_turns_on():
    assert [a.kind for a in evaluate_alerts(_row(hedge_fund_buys=0), _row(hedge_fund_buys=1), bucket="b")] == ["hedge_fund"]
    assert evaluate_alerts(_row(hedge_fund_buys=None), _row(hedge_fund_buys=1), bucket="b") == []

def test_new_watchlist_symbol_produces_nothing():
    assert evaluate_alerts(None, _row(price=150.0, dcf_upside_pct=50.0), bucket="b") == []

def test_null_sides_are_skipped():
    assert evaluate_alerts(_row(price=None), _row(price=120.0), bucket="b") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: FAIL — `ModuleNotFoundError: stonks.alerts`.

- [ ] **Step 3: Implement**

Each rule is a small private helper returning `Alert | None`; `evaluate_alerts` concatenates the non-`None` results in the order above (off_high, near_low, pe_drop, fair_value, target_upside, short_rise, big_move, hedge_fund). Titles are user-facing English: `"Trading 25% below its 52-week high"`, `"Near its 52-week low"`, `"P/E down 20% since the last sync"`, `"30% below DCF fair value"`, `"Analyst target implies 40% upside"`, `"Short interest up 3.0 points"`, `"Price moved +8.0% since the last sync"`, `"New in HedgeFollow's largest buys"`. `detail` carries the two numbers involved, e.g. `"150.00 vs high 200.00"`. `bucket` defaults to `week_bucket()`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_alerts.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/alerts.py tests/test_alerts.py
git commit -m "feat(alerts): add screener-based alert rules for watched symbols"
```

---

### Task 3: Worker evaluates alerts after each sync

**Files:**
- Modify: `src/stonks/worker.py` (`job`, ~line 20-52)
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `SQLiteStore.get_watchlist_symbols`, `SQLiteStore.get_stocks(filters={"symbol": {"values": [...]}})`, `SQLiteStore.add_alert`, `SQLiteStore.prune_alerts`, `alerts.evaluate_alerts`.
- Produces: `_watched_rows(store: SQLiteStore) -> dict[str, dict[str, Any]]` and `_record_change_alerts(store: SQLiteStore, previous: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> int` in `worker.py` (returns alerts inserted).

- [ ] **Step 1: Write the failing tests**

```python
def test_worker_records_alerts_for_watched_symbols(monkeypatch):
    store = SQLiteStore(db_path=STORE_PATH)
    store.add_to_watchlist("AAA")
    store.replace_stocks([{"symbol": "AAA", "price": 100.0, "week_52_high": 200.0}])
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda discount_rate=None: [
        {"symbol": "AAA", "price": 100.0, "week_52_high": 200.0, "pe_ratio": 12.0}
    ])
    monkeypatch.setattr("stonks.worker.current_discount_rate", lambda: 0.09)
    monkeypatch.setattr("stonks.worker.fetch_largest_buys", lambda: [])
    monkeypatch.setattr("stonks.worker.fetch_watched_news", lambda *a, **k: 0)

    job()

    alerts = store.get_alerts()
    assert [a["kind"] for a in alerts] == []          # nothing crossed yet

def test_worker_alert_is_not_duplicated_across_runs(monkeypatch, tmp_path):
    monkeypatch.setattr("stonks.worker.SQLiteStore", lambda: SQLiteStore(db_path=tmp_path / "w.db"))
    store = SQLiteStore(db_path=tmp_path / "w.db")
    store.add_to_watchlist("AAA")
    store.replace_stocks([{"symbol": "AAA", "price": 200.0, "week_52_high": 200.0}])

    cheap = {"symbol": "AAA", "price": 100.0, "week_52_high": 200.0}
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda discount_rate=None: [cheap])
    monkeypatch.setattr("stonks.worker.current_discount_rate", lambda: 0.09)
    monkeypatch.setattr("stonks.worker.fetch_largest_buys", lambda: [])
    monkeypatch.setattr("stonks.worker.fetch_watched_news", lambda *a, **k: 0)

    job()
    job()

    assert [a["kind"] for a in store.get_alerts()] == ["off_high"]
```

Write both tests against the existing `tests/test_worker.py` fixtures and style (it already builds a store on `tmp_path` and monkeypatches the fetch functions); assert on `store.get_alerts()` contents and dedupe behaviour rather than on log output. The second run must not add a second row.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_worker.py -k alert -v`
Expected: FAIL — the worker never writes alerts.

- [ ] **Step 3: Implement**

In `job()`, before fetching:

```python
store = SQLiteStore()
store.prune_alerts()
watchlist = store.get_watchlist_symbols()
previous = _watched_rows(store)
```

Then, after `store.replace_stocks(rows)` and `save_metadata`, call `_record_change_alerts(store, previous, rows)` and log the count. `_watched_rows` returns `{}` when the watchlist is empty (never call `get_stocks` with an empty `values` list). `_record_change_alerts` iterates watched symbols present in `rows`, calls `evaluate_alerts(previous.get(symbol), row)` and `add_alert(...)` for each result.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_worker.py -q`
Expected: pass, and the pre-existing worker tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/worker.py tests/test_worker.py
git commit -m "feat(worker): record alerts when a watched symbol changes"
```

---

### Task 4: News alerts from the overview payload

**Files:**
- Modify: `src/stonks/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `stonks.detail.load_page`, `stonks.detail_parse.parse_overview`, `SQLiteStore.add_alert`.
- Produces: `NEWS_ALERTS_PER_SYNC = 3` and `fetch_watched_news(store: SQLiteStore, symbols: list[str]) -> int` in `worker.py` (returns alerts inserted).

- [ ] **Step 1: Write the failing tests**

```python
def test_news_alerts_only_for_unseen_links(monkeypatch, store):
    articles = {"news": [
        {"title": "A", "url": "https://x/a", "source": "WSJ", "ago": "1 hour ago", "summary": ""},
        {"title": "B", "url": "https://x/b", "source": "BI", "ago": "2 hours ago", "summary": ""},
    ]}
    monkeypatch.setattr("stonks.worker.load_page", lambda *a, **k: ({"infoTable": [], "news": {"data": [
        {"url": "https://x/a", "title": "A", "source": "WSJ", "ago": "1 hour ago", "text": ""},
        {"url": "https://x/b", "title": "B", "source": "BI", "ago": "2 hours ago", "text": ""},
    ]}}, 1.0))
    assert fetch_watched_news(store, ["AAA"]) == 2
    assert fetch_watched_news(store, ["AAA"]) == 0
    news = [a for a in store.get_alerts() if a["kind"] == "news"]
    assert {a["dedupe_key"] for a in news} == {"AAA:news:https://x/a", "AAA:news:https://x/b"}
    assert news[0]["severity"] == "info"

def test_news_alerts_capped_per_sync(monkeypatch, store):
    items = [
        {"url": f"https://x/{i}", "title": f"T{i}", "source": "WSJ", "ago": "1 hour ago", "text": ""}
        for i in range(5)
    ]
    monkeypatch.setattr(
        "stonks.worker.load_page",
        lambda *a, **k: ({"infoTable": [], "news": {"data": items}}, 1.0),
    )
    assert fetch_watched_news(store, ["AAA"]) == 3

def test_news_alerts_skip_unreachable_symbols(monkeypatch, store):
    monkeypatch.setattr("stonks.worker.load_page", lambda *a, **k: (None, None))
    assert fetch_watched_news(store, ["ZZZZ"]) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_worker.py -k news -v`
Expected: FAIL — `fetch_watched_news` does not exist.

- [ ] **Step 3: Implement**

For each symbol, `load_page(store, symbol, "overview")` (the 900s cache keeps repeat runs cheap); skip `None` payloads; parse with `parse_overview`; take `news[:NEWS_ALERTS_PER_SYNC]`, and for each article with a `url` call `add_alert(symbol, "news", "info", title, f"{source} · {ago}", f"{symbol}:news:{url}")`, counting only inserted rows. Broken links or missing titles are skipped, never substituted. Call it from `job()` after `_record_change_alerts` and log the count.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_worker.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/worker.py tests/test_worker.py
git commit -m "feat(worker): raise news alerts for unseen watchlist headlines"
```

---

### Task 5: The alerts banner

**Files:**
- Modify: `src/stonks/app.py` (`render_screener_table` caller in `main` ~line 1330, plus a new `render_alerts_banner` near `render_pipeline_hud`)
- Test: `tests/test_alerts_ui.py`

**Interfaces:**
- Consumes: `SQLiteStore.get_alerts`, `SQLiteStore.mark_alerts_seen`, `app.open_symbol`.
- Produces: `render_alerts_banner() -> None` in `app.py`.

- [ ] **Step 1: Write the failing tests**

```python
def _app():
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at

def test_banner_hidden_without_alerts():
    at = _app()
    assert not [i for i in at.info if "🔔" in str(i.value) or "alert" in str(i.value).lower()]

def test_banner_lists_alert_and_marks_read():
    store = SQLiteStore()
    store.add_to_watchlist("AAA")
    store.add_alert(
        "AAA", "off_high", "good",
        "Trading 25% below its 52-week high", "100.00 vs high 200.00",
        "AAA:off_high:banner-test",
    )
    try:
        at = _app()
        assert any("below its 52-week high" in str(i.value) for i in at.info)
        next(b for b in at.button if "Mark all read" in b.label).click().run()
        assert store.count_unread_alerts() == 0
    finally:
        with store._connect() as conn:
            conn.execute("DELETE FROM alerts WHERE dedupe_key LIKE '%banner-test'")
            conn.commit()
        store.remove_from_watchlist("AAA")
```

Seed the alert via `SQLiteStore()` against the app's own database (`data/stonks.db`) inside a `try/finally` that deletes the rows afterwards, so the test leaves no state behind.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_alerts_ui.py -v`
Expected: FAIL — the banner does not exist.

- [ ] **Step 3: Implement**

`render_alerts_banner()` renders nothing when `store.get_alerts()` is empty. Otherwise, inside a keyed container, `st.info(f"{n} unread alert(s) for your watchlist", icon="🔔")`, then one row per alert: symbol as a `st.button` (label `f"{symbol} ▸"`, `key=f"alert_open_{id}"`) that calls `open_symbol(symbol)` and reruns, followed by `st.markdown(f"**{severity dot} {title}** — {detail}")` and a caption with the relative age. A `Mark all read` button calls `mark_alerts_seen([...])` and reruns. Call `render_alerts_banner()` at the top of `main`'s screener branch, before `render_top_filters()`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_alerts_ui.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/app.py tests/test_alerts_ui.py
git commit -m "feat(app): show unread watchlist alerts in a screener banner"
```

---

### Task 6: Watchlist badge and marker column

**Files:**
- Modify: `src/stonks/app.py` (`main` tab labels ~line 1332, `render_watchlist_tab` ~line 1050)
- Test: `tests/test_alerts_ui.py`

**Interfaces:**
- Consumes: `SQLiteStore.count_unread_alerts`, `SQLiteStore.get_alerts`.
- Produces: no new public functions; the Watchlist tab label becomes `f"⭐ Watchlist ({n})"` when `n > 0`, and the watchlist table gains an `Alerts` column showing that symbol's unread count.

- [ ] **Step 1: Write the failing tests**

```python
def test_watchlist_tab_shows_unread_count():
    store = SQLiteStore()
    store.add_to_watchlist("AAA")
    store.add_alert("AAA", "off_high", "good", "cheap", None, "AAA:off_high:badge-test")
    try:
        at = _app()
        assert "⭐ Watchlist (1)" in [tab.label for tab in at.tabs]
    finally:
        with store._connect() as conn:
            conn.execute("DELETE FROM alerts WHERE dedupe_key LIKE '%badge-test'")
            conn.commit()
        store.remove_from_watchlist("AAA")

def test_watchlist_table_marks_symbols_with_alerts():
    store = SQLiteStore()
    store.add_to_watchlist("AAA")
    store.add_alert("AAA", "off_high", "good", "cheap", None, "AAA:off_high:marker-test")
    try:
        at = _app()
        assert any("Alerts" in list(frame.value.columns) for frame in at.dataframe)
    finally:
        with store._connect() as conn:
            conn.execute("DELETE FROM alerts WHERE dedupe_key LIKE '%marker-test'")
            conn.commit()
        store.remove_from_watchlist("AAA")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_alerts_ui.py -k badge -v`
Expected: FAIL — the label has no count.

- [ ] **Step 3: Implement**

Compute `unread = store.count_unread_alerts()` once in `main` and build the tab labels from it. In `render_watchlist_tab`, build a `{symbol: count}` map from `store.get_alerts(symbol=...)` per watched symbol (the watchlist is small) and insert an `Alerts` column before the dataframe renders, `0`/blank rendering as `—`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_alerts_ui.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/app.py tests/test_alerts_ui.py
git commit -m "feat(app): badge the watchlist tab with the unread alert count"
```

---

### Task 7: Full verification and docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run a real worker pass**

```bash
uv run python -c "
from stonks.worker import job
from stonks.store import SQLiteStore
job()
s = SQLiteStore()
print('alerts:', len(s.get_alerts(unread_only=False)))
print('watchlist:', s.get_watchlist_symbols())
"
```

Expected: the sync logs `✅ Synced … symbols`, no traceback, and `alerts:` prints a number (0 is valid when nothing has changed and the watchlist is empty).

- [ ] **Step 2: Full suite and linters**

```bash
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Expected: everything passes.

- [ ] **Step 3: Container check**

```bash
docker compose build && docker compose up -d --force-recreate && curl -s -o /dev/null -w "%{http_code}\n" localhost:8502
```

Expected: `200`.

- [ ] **Step 4: README**

Add one line under the features list: alerts for watched symbols (cheapness, moves, headlines) appear as in-app banners and a watchlist badge, computed by the background worker.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe watchlist alerts"
```
