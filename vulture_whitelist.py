# Vulture whitelist for methods that are used in tests or intended for public API
from stonks.cache import LocalCache

from stonks.advisor import WhatIfResult
from stonks.alerts import Alert, evaluate_alerts, week_bucket
from stonks.backtest_view import parse_symbols, parse_weights
from stonks.config import VIRTUAL_COLUMNS
from stonks.correlation import (
    is_high_correlation,
    portfolio_correlation,
    portfolio_correlation_factor,
)
from stonks.detail import load_page
from stonks.detail_parse import (
    parse_forecast,
    parse_overview,
    parse_statement,
    parse_statistics,
)
from stonks.detail_view import (
    format_cell,
    format_compact,
    format_pct,
    metrics_sections,
    range_position,
    render_detail_page,
    statement_frame,
    yoy_pct,
)
from stonks.dossier import (
    Check,
    Dossier,
    FilingEvidence,
    Gate,
    coverage,
    filing_gate,
    forward_gate,
    gate_status,
    industry_medians,
    quality_gate,
)
from stonks.edgar import EdgarUnavailable, edgar_json, resolve_cik, user_agent
from stonks.edgar_parse import filing_checks, latest_fact, maturity_ladder
from stonks.filing_evidence import build_filing_evidence, search_filings
from stonks.portfolio import (
    Holding,
    PortfolioSummary,
    backtest_allocation,
    portfolio_snapshot,
    validate_lot,
)
from stonks.stockanalysis import SUPPORTED_COLUMNS
from stonks.store import SQLiteStore
from stonks.worker import NEWS_ALERTS_PER_SYNC, fetch_watched_news

# Dossier fields are read by the report prompt and the deep-dive view, which are
# wired in later tasks; the model itself only carries them.
Check.id  # noqa: B018
Check.threshold  # noqa: B018
Check.evidence  # noqa: B018
Gate.summary  # noqa: B018
Dossier  # noqa: B018
Dossier.as_of  # noqa: B018
Dossier.conflicts  # noqa: B018
Dossier.red_flags  # noqa: B018
Dossier.provenance  # noqa: B018
Dossier.coverage  # noqa: B018
FilingEvidence  # noqa: B018
FilingEvidence.empty  # noqa: B018
gate_status  # noqa: B018
coverage  # noqa: B018
industry_medians  # noqa: B018
quality_gate  # noqa: B018
forward_gate  # noqa: B018
filing_gate  # noqa: B018
build_filing_evidence  # noqa: B018
search_filings  # noqa: B018

LocalCache.delete  # noqa: B018
SQLiteStore.get_screen  # noqa: B018
SQLiteStore.is_in_watchlist  # noqa: B018
SQLiteStore.get_synced_symbols  # noqa: B018
SQLiteStore.get_stale_symbols  # noqa: B018
SQLiteStore.update_sync_status  # noqa: B018
SQLiteStore.save_stock  # noqa: B018
SQLiteStore.cache_get  # noqa: B018
SQLiteStore.cache_set  # noqa: B018
SQLiteStore.cache_delete  # noqa: B018
SQLiteStore.add_alert  # noqa: B018
SQLiteStore.get_alerts  # noqa: B018
SQLiteStore.mark_alerts_seen  # noqa: B018
SQLiteStore.count_unread_alerts  # noqa: B018
SQLiteStore.prune_alerts  # noqa: B018
SUPPORTED_COLUMNS  # noqa: B018
load_page  # noqa: B018
parse_overview  # noqa: B018
parse_statistics  # noqa: B018
parse_forecast  # noqa: B018
parse_statement  # noqa: B018
format_cell  # noqa: B018
format_compact  # noqa: B018
metrics_sections  # noqa: B018
range_position  # noqa: B018
render_detail_page  # noqa: B018
statement_frame  # noqa: B018
yoy_pct  # noqa: B018
Alert  # noqa: B018
week_bucket  # noqa: B018
evaluate_alerts  # noqa: B018
format_pct  # noqa: B018
SQLiteStore.unread_alert_counts  # noqa: B018
SQLiteStore.add_position  # noqa: B018
SQLiteStore.delete_position  # noqa: B018
SQLiteStore.get_positions  # noqa: B018
SQLiteStore.get_monitored_symbols  # noqa: B018
fetch_watched_news  # noqa: B018
NEWS_ALERTS_PER_SYNC  # noqa: B018
parse_symbols  # noqa: B018
parse_weights  # noqa: B018
EdgarUnavailable  # noqa: B018
edgar_json  # noqa: B018
resolve_cik  # noqa: B018
user_agent  # noqa: B018
filing_checks  # noqa: B018
latest_fact  # noqa: B018
maturity_ladder  # noqa: B018
Holding.avg_price  # noqa: B018
Holding.daily_pnl_native  # noqa: B018
PortfolioSummary.total_cost_usd  # noqa: B018
PortfolioSummary.total_value_usd  # noqa: B018
PortfolioSummary.unrealized_pnl_usd  # noqa: B018
PortfolioSummary.unrealized_pct  # noqa: B018
PortfolioSummary.excluded_symbols  # noqa: B018
validate_lot  # noqa: B018
backtest_allocation  # noqa: B018
portfolio_snapshot  # noqa: B018
is_high_correlation  # noqa: B018
portfolio_correlation  # noqa: B018
portfolio_correlation_factor  # noqa: B018
VIRTUAL_COLUMNS  # noqa: B018
WhatIfResult.after_symbols  # noqa: B018
WhatIfResult.after_weights  # noqa: B018
WhatIfResult.after_total  # noqa: B018

buy_opportunity  # noqa: B018, F821
get_buy_opportunities  # noqa: B018, F821
