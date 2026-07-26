"""Jooble — a pan-European job-board AGGREGATOR API (jooble.org).

The one aggregator on our list that natively covers Bulgaria + the Baltics — exactly our EU
gap — while also carrying DE/FR/IT/GB/ES/NL/PL. Like Adzuna it scans thousands of boards and
agencies, but it's keyword-driven (no category taxonomy), so we drive it by role terms: one
call per (term × page). Free API key from jooble.org/api/about; silent no-op until it's set.

- SEARCH: POST https://jooble.org/api/{key}  body {"keywords": "...", "location": "...",
          "page": "N"} -> {"totalCount": N, "jobs": [{id, title, location, snippet(HTML),
          salary, source, type, link, company, updated}]}. `link` is the apply URL.
"""
from __future__ import annotations

import time
from datetime import datetime

from ...core.config import settings
from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import post_json

_API = "https://jooble.org/api/{key}"
CALL_DELAY = 0.3
DEFAULT_PAGES = 1


def _configured() -> bool:
    return bool(settings.jooble_api_key)


def _posted(val) -> datetime | None:
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _to_posting(it: dict) -> RawPosting | None:
    title = (it.get("title") or "").strip()
    url = (it.get("link") or "").strip()
    if not title or not url:
        return None
    desc = html_to_text(it.get("snippet") or "").strip()
    if len(desc) < 40:
        return None
    jid = it.get("id") or url
    return RawPosting(
        source_kind="api", external_id=f"jooble:{jid}", title=title,
        company=(it.get("company") or "").strip(),
        location=(it.get("location") or "").strip(),
        url=url, apply_url=url, description=desc, posted_at=_posted(it.get("updated")),
        raw={"source": "jooble", "salary": it.get("salary"), "type": it.get("type"),
             "origin": it.get("source")})


def fetch(search_terms: list[str] | None = None, location: str = "", pages: int = DEFAULT_PAGES,
          max_terms: int | None = None, sleep=time.sleep) -> list[RawPosting]:
    """One POST per (term × page). With no terms, pulls Jooble's recent feed for `location`.
    `max_terms` caps the terms queried this run — Jooble's free tier allows only 500 requests
    TOTAL, so an unbounded per-term sweep would exhaust the quota; keep runs small."""
    if not _configured():
        return []                                # key not set -> silent no-op
    terms = [t for t in (search_terms or [""]) if search_terms is None or t] or [""]
    if max_terms is not None and max_terms >= 0:
        terms = terms[:max_terms]
    url = _API.format(key=settings.jooble_api_key)
    out: list[RawPosting] = []
    seen: set[str] = set()
    for term in terms:
        for page in range(1, pages + 1):
            body = {"page": str(page)}
            if term:
                body["keywords"] = term
            if location:
                body["location"] = location
            j = post_json(url, body)
            jobs = j.get("jobs") if isinstance(j, dict) else None
            if not jobs:
                break
            for it in jobs:
                rp = _to_posting(it)
                if rp is not None and rp.external_id not in seen:
                    seen.add(rp.external_id)
                    out.append(rp)
            sleep(CALL_DELAY)
    return out


register("jooble", fetch)
