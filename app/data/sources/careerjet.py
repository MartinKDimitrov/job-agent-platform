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
from .http import fetch_json

_API = "https://search.api.careerjet.net/v4/query"
# our markets -> Careerjet locale codes (it covers BG natively, unlike Adzuna)
LOCALES = {"gb": "en_GB", "de": "de_DE", "fr": "fr_FR", "it": "it_IT", "es": "es_ES",
           "nl": "nl_NL", "pl": "pl_PL", "bg": "bg_BG"}
PAGE_SIZE = 50
CALL_DELAY = 0.3
_UA = "JobAgent/0.1 (+https://localhost)"


def _configured() -> bool:
    return bool(settings.careerjet_api_key)


def _auth_header() -> dict:
    token = base64.b64encode(f"{settings.careerjet_api_key}:".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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
          page_size: int = PAGE_SIZE, sleep=time.sleep) -> list[RawPosting]:
    """One call per (term × country/locale × page). With no terms, pulls each locale's feed."""
    if not _configured():
        return []                                # key not set -> silent no-op
    terms = [t for t in (search_terms or [""]) if search_terms is None or t] or [""]
    headers = _auth_header()
    user_ip = settings.careerjet_user_ip or "8.8.8.8"   # required; server-side geo default
    out: list[RawPosting] = []
    seen: set[str] = set()
    for country in countries:
        locale = LOCALES.get(country, country)
        for term in terms:
            for page in range(1, pages + 1):
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
