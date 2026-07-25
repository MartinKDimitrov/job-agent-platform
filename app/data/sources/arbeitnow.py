"""Arbeitnow — a free, unauthenticated Germany/EU job-board aggregator API.

The pivot away from per-company ATS adapters: aggregators already carry "all the jobs" and offer
a clean API, so one source covers thousands of employers. Arbeitnow's board API is free and
keyless (verified live), returning full job metadata with pagination.

- LIST: GET https://www.arbeitnow.com/api/job-board-api?page=N -> {data:[{slug, company_name,
        title, description(HTML), url, location, remote, tags[], job_types[], created_at}],
        meta:{current_page, last_page?}}. `url` is the apply link.
Board-style source (no per-company registry), like karriere.nrw/remoteok; fetched blanket.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

_API = "https://www.arbeitnow.com/api/job-board-api"
DEFAULT_MAX_PAGES = 20           # 100 jobs/page — bounded blanket pull
PAGE_DELAY = 0.3


def _posted(val) -> datetime | None:
    if val is None:
        return None
    try:                                    # created_at is a unix timestamp (seconds)
        return datetime.fromtimestamp(int(val), tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OSError):
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None


def fetch(max_pages: int = DEFAULT_MAX_PAGES, delay: float = PAGE_DELAY,
          sleep=time.sleep) -> list[RawPosting]:
    """Paged blanket pull of the Arbeitnow board. Stops at an empty page or max_pages."""
    out: list[RawPosting] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        j = fetch_json(f"{_API}?page={page}", browser=True)
        items = j.get("data") if isinstance(j, dict) else None
        if not items:
            break
        for it in items:
            slug = (it.get("slug") or "").strip()
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            if not title or not url or slug in seen:
                continue
            desc = html_to_text(it.get("description") or "").strip()
            if len(desc) < 40:
                continue
            seen.add(slug)
            out.append(RawPosting(
                source_kind="api", external_id=slug or url, title=title,
                company=(it.get("company_name") or "").strip(),
                location=(it.get("location") or "").strip(), url=url, apply_url=url,
                description=desc, posted_at=_posted(it.get("created_at")),
                raw={"source": "arbeitnow", "remote": bool(it.get("remote"))}))
        sleep(delay)
    return out


register("arbeitnow", fetch)
