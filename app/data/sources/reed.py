"""Reed — the UK's biggest direct job board, with an open Jobseeker API (reed.co.uk/developers).

Depth play for the UK market: Adzuna already covers GB in breadth, but Reed carries the
employers' DIRECT postings (not aggregated re-posts), with clean salary/contract metadata.
Free key by simple registration; silent no-op until it's set.

- SEARCH: GET https://www.reed.co.uk/api/1.0/search?keywords=&locationName=
          &resultsToTake=&resultsToSkip=  (Basic auth: API key as username, empty password)
          -> {totalResults, results:[{jobId, employerName, jobTitle, locationName,
          minimumSalary, maximumSalary, currency, date(dd/mm/yyyy), expirationDate,
          jobDescription, jobUrl}]}. jobDescription here is a truncated snippet — same
          contract as Jooble's; the extractor works on it and the posting links out.
"""
from __future__ import annotations

import base64
import time
from datetime import datetime

from ...core.config import settings
from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

_API = "https://www.reed.co.uk/api/1.0/search"
RESULTS_PER_PAGE = 100          # API hard cap per request
CALL_DELAY = 0.3
DEFAULT_PAGES = 1


def _configured() -> bool:
    return bool(settings.reed_api_key)


def _auth_header() -> dict:
    # API key travels as the Basic-auth USERNAME with an empty password.
    token = base64.b64encode(f"{settings.reed_api_key}:".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _posted(val) -> datetime | None:
    try:
        return datetime.strptime(str(val), "%d/%m/%Y")      # Reed dates are UK-style
    except (ValueError, TypeError):
        return None


def _to_posting(it: dict) -> RawPosting | None:
    title = (it.get("jobTitle") or "").strip()
    url = (it.get("jobUrl") or "").strip()
    if not title or not url:
        return None
    desc = html_to_text(it.get("jobDescription") or "").strip()
    if len(desc) < 40:
        return None
    city = (it.get("locationName") or "").strip()
    return RawPosting(
        source_kind="api", external_id=f"reed:{it.get('jobId')}", title=title,
        company=(it.get("employerName") or "").strip(),
        # Reed is UK-only and locationName is a bare city — append the country so the
        # geo tiers can place it (same shape the EURES adapter emits: "Варна, BG").
        location=f"{city}, UK" if city else "UK",
        url=url, apply_url=url, description=desc, posted_at=_posted(it.get("date")),
        raw={"source": "reed", "country": "GB",
             "salary_min": it.get("minimumSalary"), "salary_max": it.get("maximumSalary"),
             "currency": it.get("currency"), "expiration": it.get("expirationDate")})


def fetch(search_terms: list[str] | None = None, location: str = "",
          pages: int = DEFAULT_PAGES, max_terms: int | None = None,
          sleep=time.sleep) -> list[RawPosting]:
    """One GET per (term × page). With no terms, pulls Reed's recent feed (newest first)."""
    if not _configured():
        return []                                # key not set -> silent no-op
    terms = [t for t in (search_terms or [""]) if search_terms is None or t] or [""]
    if max_terms is not None and max_terms >= 0:
        terms = terms[:max_terms]
    headers = _auth_header()
    out: list[RawPosting] = []
    seen: set[str] = set()
    for term in terms:
        for page in range(pages):
            params: dict = {"resultsToTake": RESULTS_PER_PAGE,
                            "resultsToSkip": page * RESULTS_PER_PAGE}
            if term:
                params["keywords"] = term
            if location:
                params["locationName"] = location
            j = fetch_json(_API, params=params, headers=headers)
            results = j.get("results") if isinstance(j, dict) else None
            if not results:
                break
            for it in results:
                rp = _to_posting(it)
                if rp is not None and rp.external_id not in seen:
                    seen.add(rp.external_id)
                    out.append(rp)
            sleep(CALL_DELAY)
    return out


register("reed", fetch)
