"""Fetch and cache primary-filing evidence for one symbol.

Every SEC request goes through :func:`stonks.edgar.edgar_json` so the shared rate
limit, contact header and seven-day cache apply. Nothing here imports Streamlit,
and failures become a reason on :class:`FilingEvidence` rather than an exception
escaping into the dossier.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from urllib.parse import urlencode

from stonks import edgar
from stonks.dossier import (
    GUIDANCE_PHRASES,
    INFORMATIONAL_PHRASES,
    RED_FLAG_PHRASES,
    FilingEvidence,
)
from stonks.store import SQLiteStore

CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days, like every non-map EDGAR entry
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
PHRASE_FORMS = ("10-K", "10-Q")
GUIDANCE_FORMS = ("8-K", "10-Q")

_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _count(total: Any) -> int:
    """Read EFTS' total hit count, refusing to guess when the shape drifts.

    The hit list can be truncated or scoped by filters, so its length is not a
    substitute for the reported total: a missing total must never look like a
    clean zero-hit sweep.
    """
    if isinstance(total, Mapping):
        total = total.get("value")
    if isinstance(total, bool):
        raise edgar.EdgarUnavailable("EFTS response has an unexpected shape")
    if isinstance(total, int) and total >= 0:
        return total
    if isinstance(total, str) and total.isdigit():
        return int(total)
    raise edgar.EdgarUnavailable("EFTS response has an unexpected shape")


def _filing_url(cik: str, accession: str) -> str:
    """Link straight to the filing index named in the search result."""
    digits = cik.strip().lstrip("0") or "0"
    if not digits.isdigit() or not _ACCESSION.fullmatch(accession):
        raise edgar.EdgarUnavailable("EFTS returned an unexpected accession")
    compact = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{digits}/"
        f"{compact}/{accession}-index.html"
    )


def search_filings(
    phrase: str,
    cik: str,
    *,
    forms: Sequence[str],
    store: SQLiteStore,
    fetch: Any = None,
    latest_dates: Mapping[str, str] | None = None,
    filing_digest: str | None = None,
) -> list[dict[str, Any]]:
    """Return dated, linked EFTS hits for one exact phrase and set of forms.

    When ``latest_dates`` maps a form to its newest filing date, only hits from
    that filing are kept; older filings must not fail a freshness-scoped sweep.
    ``filing_digest`` salts the cache key with those filing dates and accessions
    so a companyfacts refresh cannot leave stale hits in scope. An unrecognised
    response shape is an error, not a zero-hit result: silently treating a
    changed payload as "no matches" would pass a red-flag check.
    """
    query = urlencode({"q": f'"{phrase}"', "forms": ",".join(forms), "ciks": cik})
    cache_key = f"edgar:{cik}:efts:{phrase}:{','.join(forms)}"
    if filing_digest is not None:
        cache_key = f"{cache_key}:{filing_digest}"
    payload = edgar.edgar_json(
        f"{EFTS_URL}?{query}",
        store=store,
        cache_key=cache_key,
        ttl_seconds=CACHE_TTL_SECONDS,
        fetch=fetch,
    )
    hits = payload.get("hits") if isinstance(payload, Mapping) else None
    if not isinstance(hits, Mapping):
        raise edgar.EdgarUnavailable("EFTS response has an unexpected shape")
    entries = hits.get("hits")
    if not isinstance(entries, Sequence) or isinstance(entries, str | bytes):
        raise edgar.EdgarUnavailable("EFTS response has an unexpected shape")
    count = _count(hits.get("total"))
    allowed = set(forms)

    found: list[dict[str, Any]] = []
    for entry in entries:
        source = entry.get("_source") if isinstance(entry, Mapping) else None
        fields = (
            source
            if isinstance(source, Mapping)
            else entry
            if isinstance(entry, Mapping)
            else None
        )
        if not isinstance(fields, Mapping):
            raise edgar.EdgarUnavailable("EFTS response has an unexpected shape")
        form = _text(fields.get("form")) or _text(fields.get("file_type"))
        if not form:
            raise edgar.EdgarUnavailable("EFTS response has an unexpected shape")
        if form not in allowed:
            continue
        filed = (
            _text(fields.get("file_date"))
            or _text(fields.get("filing_date"))
            or _text(fields.get("filed"))
        )
        accession = (
            _text(fields.get("adsh"))
            or _text(fields.get("accession_number"))
            or _text(fields.get("accession"))
        )
        if isinstance(entry, Mapping) and not accession:
            accession = _text(entry.get("_id"))
        if not filed or not accession:
            raise edgar.EdgarUnavailable("EFTS response has an unexpected shape")
        try:
            filed = date.fromisoformat(filed[:10]).isoformat()
        except ValueError as exc:
            raise edgar.EdgarUnavailable(
                "EFTS response has an unexpected shape"
            ) from exc
        if latest_dates is not None and filed != latest_dates.get(form):
            continue
        found.append(
            {
                "phrase": phrase,
                "count": count,
                "filing_date": filed,
                "accession": accession,
                "form": form,
                "url": _filing_url(cik, accession),
            }
        )
    if latest_dates is not None:
        # The EFTS total counts historical filings too; report only what we kept.
        for hit in found:
            hit["count"] = len(found)
    return found


def _latest_form_filings(
    payload: Mapping[str, Any],
) -> tuple[dict[str, str], str]:
    """Newest unamended 10-K/10-Q dates and a digest of their dates/accessions.

    The digest is stable across payload ordering and salted into EFTS cache keys:
    once companyfacts reports a newer filing, hits cached against the old filing
    must be re-fetched rather than silently filtered down to zero.
    """
    latest: dict[str, tuple[str, str]] = {}
    namespaces = payload.get("facts")
    if not isinstance(namespaces, Mapping):
        raise edgar.EdgarUnavailable("SEC companyfacts payload has an unexpected shape")
    for namespace in namespaces.values():
        if not isinstance(namespace, Mapping):
            continue
        for tag in namespace.values():
            if not isinstance(tag, Mapping):
                continue
            units = tag.get("units")
            if not isinstance(units, Mapping):
                continue
            for entries in units.values():
                if not isinstance(entries, Sequence) or isinstance(
                    entries, str | bytes
                ):
                    continue
                for entry in entries:
                    if (
                        not isinstance(entry, Mapping)
                        or entry.get("form") not in PHRASE_FORMS
                    ):
                        continue
                    filed = _text(entry.get("filed"))
                    if not filed:
                        continue
                    try:
                        filed = date.fromisoformat(filed[:10]).isoformat()
                    except ValueError:
                        continue
                    form = entry["form"]
                    candidate = (filed, _text(entry.get("accn")))
                    if form not in latest or candidate > latest[form]:
                        latest[form] = candidate
    dates = {form: filed for form, (filed, _) in latest.items()}
    fingerprint = hashlib.sha256(
        json.dumps(sorted(latest.items()), separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return dates, fingerprint


def build_filing_evidence(
    symbol: str, *, store: SQLiteStore, fetch: Any = None
) -> FilingEvidence:
    """Fetch the facts and phrase hits behind one symbol's filing gate.

    This never raises: an absent contact string, an unknown ticker or any SEC
    failure yields evidence with a reason and no facts or hits, so the gate
    reports ``unverified`` with that reason.
    """
    try:
        edgar.user_agent()
        cik = edgar.resolve_cik(symbol, store=store, fetch=fetch)
        if cik is None:
            return FilingEvidence(reason="no CIK")
        payload = edgar.edgar_json(
            COMPANYFACTS_URL.format(cik=cik),
            store=store,
            cache_key=f"edgar:{cik}:companyfacts",
            ttl_seconds=CACHE_TTL_SECONDS,
            fetch=fetch,
        )
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("facts"), Mapping
        ):
            raise edgar.EdgarUnavailable(
                "SEC companyfacts payload has an unexpected shape"
            )
        latest_dates, filing_digest = _latest_form_filings(payload)
        # Only the newest filing for each form is in scope for phrase checks;
        # guidance (8-K/10-Q) is a separate, unfiltered sweep below. Both sweeps
        # key their cache on the companyfacts filing fingerprint.
        hits: list[dict[str, Any]] = []
        for phrase in RED_FLAG_PHRASES + INFORMATIONAL_PHRASES:
            hits.extend(
                search_filings(
                    phrase,
                    cik,
                    forms=PHRASE_FORMS,
                    store=store,
                    fetch=fetch,
                    latest_dates=latest_dates,
                    filing_digest=filing_digest,
                )
            )
        guidance: list[dict[str, Any]] = []
        for phrase in GUIDANCE_PHRASES:
            guidance.extend(
                search_filings(
                    phrase,
                    cik,
                    forms=GUIDANCE_FORMS,
                    store=store,
                    fetch=fetch,
                    filing_digest=filing_digest,
                )
            )
        return FilingEvidence(
            cik=cik,
            facts=payload,
            hits=tuple(hits),
            latest_10k=latest_dates.get("10-K"),
            latest_10q=latest_dates.get("10-Q"),
            guidance_hits=tuple(guidance),
        )
    except edgar.UserAgentUnavailable:
        return FilingEvidence(reason=edgar.USER_AGENT_REASON)
    except edgar.EdgarUnavailable as exc:
        return FilingEvidence(reason=str(exc) or "EDGAR unavailable")
