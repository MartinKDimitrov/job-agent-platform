"""Careerjet — a global job-board AGGREGATOR API covering 90+ countries (careerjet.com).

Third aggregator in the pivot (after Adzuna/Jooble): one API, all our markets INCLUDING BG.
Keyword-driven (no category taxonomy), so wired as a profile source: one call per (term ×
locale). Free publisher key from careerjet.com/partners/api; silent no-op until it's set.

- SEARCH: GET https://search.api.careerjet.net/v4/query
          Basic-auth (username = API key), params locale_code/keywords/location/page/page_size
          + required user_ip & user_agent ->
          {type, hits, pages, jobs:[{title, company, date, description, locations, url, site,
          salary, salary_min, salary_max, salary_currency_code, salary_type}]}. `url` = apply.
"""
from __future__ import annotations

import base64
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

from ...core.config import settings
from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json, fetch_text

_API = "https://search.api.careerjet.net/v4/query"
# our markets -> Careerjet locale codes (it covers BG natively, unlike Adzuna)
LOCALES = {"gb": "en_GB", "de": "de_DE", "fr": "fr_FR", "it": "it_IT", "es": "es_ES",
           "nl": "nl_NL", "pl": "pl_PL", "bg": "bg_BG"}
PAGE_SIZE = 50
CALL_DELAY = 0.3
_UA = "Mozilla/5.0 (compatible; JobAgent/0.1; +https://localhost)"
_outbound_ip: str | None = None            # cached per process


def _configured() -> bool:
    return bool(settings.careerjet_api_key)


def _auth_header() -> dict:
    # v4 wants: API key as Basic-auth username (empty password) AND a Referer header. Without a
    # Referer the API 403s ("Undeclared referrer") even with a valid key.
    token = base64.b64encode(f"{settings.careerjet_api_key}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Referer": settings.site_url}


def _user_ip() -> str:
    """A REAL caller IP — v4 rejects placeholders like 8.8.8.8 ('Invalid user_ip'). Prefer the
    configured value (should match the whitelisted server IP); else detect the outbound IP once."""
    global _outbound_ip
    if settings.careerjet_user_ip:
        return settings.careerjet_user_ip
    if _outbound_ip is None:
        _outbound_ip = (fetch_text("https://api.ipify.org") or "").strip()
    return _outbound_ip


def _posted(val) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        try:                                    # Careerjet dates are often RFC-822
            return parsedate_to_datetime(str(val)).replace(tzinfo=None)
        except (ValueError, TypeError):
            return None


def _location(it: dict) -> str:
    loc = it.get("locations")
    if isinstance(loc, list):
        return ", ".join(str(x) for x in loc if x)[:255]
    return (loc or "").strip()


def _to_posting(country: str, it: dict) -> RawPosting | None:
    title = (it.get("title") or "").strip()
    url = (it.get("url") or "").strip()
    if not title or not url:
        return None
    desc = html_to_text(it.get("description") or "").strip()
    if len(desc) < 40:
        return None
    return RawPosting(
        source_kind="api", external_id=f"careerjet:{url}", title=title,
        company=(it.get("company") or "").strip(), location=_location(it),
        url=url, apply_url=url, description=desc, posted_at=_posted(it.get("date")),
        raw={"source": "careerjet", "country": country.upper(), "site": it.get("site"),
             "salary": it.get("salary"), "salary_min": it.get("salary_min"),
             "salary_max": it.get("salary_max"),
             "salary_currency": it.get("salary_currency_code")})


def fetch(search_terms: list[str] | None = None, countries=tuple(LOCALES), pages: int = 1,
          page_size: int = PAGE_SIZE, start_page: int = 1, sleep=time.sleep) -> list[RawPosting]:
    """One call per (term × country/locale × page). With no terms, pulls each locale's feed.
    `start_page` lets the bulk drain resume deep pagination from a saved cursor."""
    if not _configured():
        return []                                # key not set -> silent no-op
    terms = [t for t in (search_terms or [""]) if search_terms is None or t] or [""]
    headers = _auth_header()
    user_ip = _user_ip()                                # required; a real IP (not a placeholder)
    out: list[RawPosting] = []
    seen: set[str] = set()
    for country in countries:
        locale = LOCALES.get(country, country)
        for term in terms:
            for page in range(start_page, start_page + pages):
                params = {"locale_code": locale, "page": page, "page_size": page_size,
                          "user_ip": user_ip, "user_agent": _UA}
                if term:
                    params["keywords"] = term
                j = fetch_json(_API, params=params, headers=headers)
                jobs = j.get("jobs") if isinstance(j, dict) else None
                if not jobs:
                    break
                for it in jobs:
                    rp = _to_posting(country, it)
                    if rp is not None and rp.external_id not in seen:
                        seen.add(rp.external_id)
                        out.append(rp)
                sleep(CALL_DELAY)
    return out


register("careerjet", fetch)
