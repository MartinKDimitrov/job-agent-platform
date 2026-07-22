"""Workable adapter (ROADMAP 16в) — via the public endpoints behind apply.workable.com.

The old v1 widget API answers 200 but with an empty jobs list even for hiring accounts
(why the adapter was deferred in 2026-07). What actually works (verified live on TINQIN):
- LIST:   POST https://apply.workable.com/api/v3/accounts/{slug}/jobs  {"query": ""}
          -> {"total": N, "results": [{shortcode, title, location(s), remote, published}]},
          paginated via a "nextPage" token echoed back in the body.
- DETAIL: GET  https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}
          -> description / requirements / benefits as SEPARATE html fields — so benefits
          never even enter the posting text (no reliance on the extractor's benefit filter).

One detail GET per posting, so `max_jobs` caps the total requests per account.
Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

import time
from datetime import datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json, post_json

_LIST_URL = "https://apply.workable.com/api/v3/accounts/{slug}/jobs"
_DETAIL_URL = "https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}"
_JOB_URL = "https://apply.workable.com/{slug}/j/{shortcode}/"
_DETAIL_DELAY = 0.3   # s between per-job detail GETs — Workable 429s bursty clients (seen live)


def _location(item: dict) -> str:
    if item.get("remote"):
        return "Remote"
    loc = item.get("location") or {}
    parts = [loc.get("city"), loc.get("country")]
    return ", ".join(p for p in parts if p)


def _posted(item: dict):
    raw = item.get("published") or ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None


def _description(slug: str, shortcode: str) -> str:
    d = fetch_json(_DETAIL_URL.format(slug=slug, shortcode=shortcode), browser=True)
    if not isinstance(d, dict):
        return ""
    parts = []
    if d.get("description"):
        parts.append(html_to_text(d["description"]))
    if d.get("requirements"):
        # explicit header so the extractor buckets these as must (its own "Nice to Have"
        # subheader inside flips to nice); benefits are deliberately NOT appended
        parts.append("Requirements:\n" + html_to_text(d["requirements"]))
    return "\n".join(p for p in parts if p)


def fetch(slug: str, company_name: str | None = None, max_jobs: int = 100,
          detail_delay: float = _DETAIL_DELAY) -> list[RawPosting]:
    out: list[RawPosting] = []
    token = None
    while len(out) < max_jobs:
        body = {"query": ""} if token is None else {"query": "", "token": token}
        page = post_json(_LIST_URL.format(slug=slug), body)
        if not isinstance(page, dict) or not page.get("results"):
            break
        for item in page["results"]:
            shortcode = item.get("shortcode") or ""
            title = (item.get("title") or "").strip()
            if not (shortcode and title):
                continue
            url = _JOB_URL.format(slug=slug, shortcode=shortcode)
            if detail_delay and out:
                time.sleep(detail_delay)
            out.append(RawPosting(
                source_kind="ats_api", external_id=shortcode, title=title,
                company=company_name or slug, location=_location(item),
                url=url, apply_url=url + "apply/",
                description=_description(slug, shortcode), posted_at=_posted(item),
                raw={"workplace": item.get("workplace", "")},
            ))
            if len(out) >= max_jobs:
                break
        token = page.get("nextPage")
        if not token:
            break
    return out


register("workable", fetch)
