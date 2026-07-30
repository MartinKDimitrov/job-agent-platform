"""EURES — the official EU employment portal (europa.eu/eures), aggregating the national public
employment services of all EU/EEA countries. 2M+ vacancies, updated daily; no official keyed
API, but the portal's own public search API is anonymous and readable (verified live 2026-07).

This is our path to the EU countries the other aggregators miss — Adzuna 404s on BG/RO/SE/
Baltics/etc.; EURES covers them natively. Country-driven (like arbeitsagentur/karriere.nrw), so
fetched blanket per country.

- SEARCH: POST europa.eu/eures/api/jv-searchengine/public/jv-search/search
          body {resultsPerPage, page, locationCodes:[cc], keywords, requestLanguage} ->
          {numberRecords, jvs:[{id, title, description, creationDate(ms), locationMap, employer,
          availableLanguages, translations}]}. Apply link = the portal detail page for `id`.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import post_json

_SEARCH = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
_DETAIL = "https://europa.eu/eures/portal/jv-se/jv-details/{id}"
# The EU/EEA countries our other sources don't cover well (Adzuna handles de/fr/it/gb/es/nl/pl/
# at/be/ch). EURES fills the rest — including Bulgaria + the Baltics.
EURES_COUNTRIES = ("bg", "ro", "gr", "pt", "ie", "se", "dk", "fi", "cz", "hu", "hr", "sk", "si",
                   "lt", "lv", "ee", "lu")
DEFAULT_PAGES = 2
PAGE_SIZE = 50
CALL_DELAY = 0.3


def _posted(ms) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OSError):
        return None


def _location(jv: dict) -> str:
    loc = jv.get("locationMap")
    if isinstance(loc, dict) and loc:
        return ", ".join(sorted(loc.keys())).upper()[:255]
    return ""


def _to_posting(jv: dict) -> RawPosting | None:
    jid = jv.get("id")
    title = (jv.get("title") or "").strip()
    if not jid or not title:
        return None
    # prefer an English translation when present (readability), else the original language
    tr = jv.get("translations") or {}
    en = tr.get("en") if isinstance(tr, dict) else None
    desc_src = (en or {}).get("description") if isinstance(en, dict) else None
    desc = html_to_text(desc_src or jv.get("description") or "").strip()
    if len(desc) < 40:
        return None
    url = _DETAIL.format(id=jid)
    return RawPosting(
        source_kind="api", external_id=f"eures:{jid}", title=title,
        company=((jv.get("employer") or {}).get("name") or "").strip(),
        location=_location(jv), url=url, apply_url=url, description=desc,
        posted_at=_posted(jv.get("creationDate")),
        raw={"source": "eures", "languages": jv.get("availableLanguages")})


def fetch_page(country: str, page: int, results_per_page: int = PAGE_SIZE) -> list[RawPosting]:
    """One page of one country's EURES feed — the unit the concurrent drain fetches (resumable,
    per-country cursor). Empty list = that country's feed is exhausted at this depth."""
    body = {"resultsPerPage": results_per_page, "page": page, "sortSearch": "BEST_MATCH",
            "keywords": [], "locationCodes": [country], "requestLanguage": "en", "sessionId": ""}
    j = post_json(_SEARCH, body)
    jvs = j.get("jvs") if isinstance(j, dict) else None
    if not jvs:
        return []
    return [rp for jv in jvs if (rp := _to_posting(jv)) is not None]


def fetch(countries=EURES_COUNTRIES, pages: int = DEFAULT_PAGES, results_per_page: int = PAGE_SIZE,
          sleep=time.sleep) -> list[RawPosting]:
    """Blanket pull: `pages` pages of vacancies per country. Dedups within the run."""
    out: list[RawPosting] = []
    seen: set[str] = set()
    for cc in countries:
        for page in range(1, pages + 1):
            body = {"resultsPerPage": results_per_page, "page": page, "sortSearch": "BEST_MATCH",
                    "keywords": [], "locationCodes": [cc], "requestLanguage": "en",
                    "sessionId": ""}
            j = post_json(_SEARCH, body)
            jvs = j.get("jvs") if isinstance(j, dict) else None
            if not jvs:
                break
            for jv in jvs:
                rp = _to_posting(jv)
                if rp is not None and rp.external_id not in seen:
                    seen.add(rp.external_id)
                    out.append(rp)
            sleep(CALL_DELAY)
    return out


register("eures", fetch)
