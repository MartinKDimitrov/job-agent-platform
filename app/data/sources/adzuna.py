"""Adzuna — a multi-country job-board AGGREGATOR API (developer.adzuna.com).

The breadth play: Adzuna aggregates listings across many boards (Indeed et al. that we can't
read directly), and one API covers all our markets — DE/FR/IT/GB/ES/NL/PL — with 1M+ live
postings per big country. Free trial keys; silent no-op until they're set.

- SEARCH: GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
          ?app_id&app_key&results_per_page&what={term} ->
          {count, results:[{id, title, description, company:{display_name},
          location:{display_name}, redirect_url, created, salary_min, salary_max}]}.
`redirect_url` is Adzuna's apply link (their attribution model). Queried per role term (like
arbeitsagentur/francetravail): one call per unique term × country per run — relevant, and
economical on the trial quota.
"""
from __future__ import annotations

import time
from datetime import datetime

from ...core.config import settings
from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

_BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
COUNTRIES = ("de", "fr", "it", "gb", "es", "nl", "pl")   # our target markets
_ISO2_COUNTRY = {"de": "DE", "fr": "FR", "it": "IT", "gb": "GB", "es": "ES", "nl": "NL",
                 "pl": "PL"}
RESULTS_PER_PAGE = 50
CALL_DELAY = 0.3


def _configured() -> bool:
    return bool(settings.adzuna_app_id and settings.adzuna_app_key)


def _posted(val) -> datetime | None:
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _to_posting(country: str, it: dict) -> RawPosting | None:
    title = (it.get("title") or "").strip()
    url = (it.get("redirect_url") or "").strip()
    if not title or not url:
        return None
    desc = html_to_text(it.get("description") or "").strip()
    if len(desc) < 40:
        return None
    return RawPosting(
        source_kind="api", external_id=f"{country}:{it.get('id')}", title=title,
        company=((it.get("company") or {}).get("display_name") or "").strip(),
        location=((it.get("location") or {}).get("display_name") or "").strip(),
        url=url, apply_url=url, description=desc, posted_at=_posted(it.get("created")),
        raw={"source": "adzuna", "country": _ISO2_COUNTRY.get(country, country.upper()),
             "salary_min": it.get("salary_min"), "salary_max": it.get("salary_max")})


def _auth() -> dict:
    return {"app_id": settings.adzuna_app_id, "app_key": settings.adzuna_app_key,
            "content-type": "application/json"}


def categories(country: str = "de") -> list[tuple[str, str]]:
    """(tag, label) of Adzuna's ~30 job categories — the slices that cover ALL professions."""
    if not _configured():
        return []
    j = fetch_json(f"https://api.adzuna.com/v1/api/jobs/{country}/categories", params=_auth())
    return ([(c.get("tag"), c.get("label")) for c in j.get("results") or []]
            if isinstance(j, dict) else [])


def fetch_page(country: str, page: int, *, category: str | None = None, what: str | None = None,
               results_per_page: int = RESULTS_PER_PAGE,
               sort_by: str | None = None) -> tuple[list[RawPosting] | None, int]:
    """One search page -> (postings, Adzuna's total count for the query). The unit the bulk
    pull iterates; count sizes the plan/progress. Returns ``(None, 0)`` when the CALL FAILED
    (network/HTTP error, e.g. a transient 503) — distinct from ``([], total)`` for a genuinely
    empty page — so the caller never mistakes a hiccup for a drained slice. ``sort_by="date"``
    returns newest-first — what the recency refresh pages until it meets already-seen jobs."""
    if not _configured():
        return [], 0
    params = {**_auth(), "results_per_page": results_per_page}
    if category:
        params["category"] = category
    if what:
        params["what"] = what
    if sort_by:
        params["sort_by"] = sort_by
    j = fetch_json(_BASE.format(country=country, page=page), params=params)
    if j is None:
        return None, 0                          # call failed — NOT an empty page
    if not isinstance(j, dict):
        return [], 0
    out = []
    for it in j.get("results") or []:
        rp = _to_posting(country, it)
        if rp is not None:
            out.append(rp)
    return out, int(j.get("count") or 0)


def fetch(search_terms: list[str] | None = None, countries=COUNTRIES, pages: int = 1,
          results_per_page: int = RESULTS_PER_PAGE, sleep=time.sleep) -> list[RawPosting]:
    """One call per (term × country × page). With no terms, pulls each country's recent feed."""
    if not _configured():
        return []                                # keys not set -> silent no-op
    terms = [t for t in (search_terms or [""]) if search_terms is None or t] or [""]
    auth = {"app_id": settings.adzuna_app_id, "app_key": settings.adzuna_app_key,
            "results_per_page": results_per_page, "content-type": "application/json"}
    out: list[RawPosting] = []
    seen: set[str] = set()
    for country in countries:
        for term in terms:
            for page in range(1, pages + 1):
                params = dict(auth)
                if term:
                    params["what"] = term
                j = fetch_json(_BASE.format(country=country, page=page), params=params)
                results = j.get("results") if isinstance(j, dict) else None
                if not results:
                    break
                for it in results:
                    rp = _to_posting(country, it)
                    if rp is not None and rp.external_id not in seen:
                        seen.add(rp.external_id)
                        out.append(rp)
                sleep(CALL_DELAY)
    return out


register("adzuna", fetch)
