"""JobTech / Platsbanken adapter — Sweden's public employment service (Arbetsförmedlingen).

The JobSearch API is FULLY open (no key, no registration — the reference open-data job API
in the EU; docs: https://jobsearch.api.jobtechdev.se). We query it as a TARGETED source:
one search per unique profile role term per ingest cycle, like dev.bg — a full dump is
~100k live postings and would drown the index. Descriptions arrive as plain text;
`webpage_url` is the canonical Platsbanken posting, `application_details.url` (when the
employer gave one) is the direct apply link.

First adapter of the EU boards plan (ROADMAP 🇪🇺 audit: JobTech → Arbeitsagentur →
France Travail → EURES). Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

from datetime import datetime

from ...domain.entities import RawPosting
from .base import register
from .http import fetch_json

API = "https://jobsearch.api.jobtechdev.se/search"
DEFAULT_LIMIT = 100          # API max per request; one page per term is plenty


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _location(hit: dict) -> str:
    addr = hit.get("workplace_address") or {}
    parts = [addr.get("municipality"), addr.get("region"), "Sweden"]
    return ", ".join(p for p in parts if p)


def fetch(search_terms: list[str] | None = None, limit: int = DEFAULT_LIMIT) -> list[RawPosting]:
    """One open-API search per term, normalized to RawPosting. Duplicate hits across terms
    collapse by id here; cross-source dedup happens in ingest as usual."""
    out: dict[str, RawPosting] = {}
    for term in search_terms or []:
        data = fetch_json(API, params={"q": term, "limit": limit})
        if not isinstance(data, dict):
            continue
        for hit in data.get("hits") or []:
            hid = str(hit.get("id") or "")
            if not hid or hid in out:
                continue
            desc = (hit.get("description") or {}).get("text") or ""
            apply_url = ((hit.get("application_details") or {}).get("url")
                         or hit.get("webpage_url") or "")
            out[hid] = RawPosting(
                source_kind="board_api",
                external_id=hid,
                title=hit.get("headline") or "",
                company=(hit.get("employer") or {}).get("name") or "",
                location=_location(hit),
                url=hit.get("webpage_url") or "",
                apply_url=apply_url,
                description=desc,
                posted_at=_parse_dt(hit.get("publication_date")),
                raw={"source": "jobtech", "term": term},
            )
    return list(out.values())


register("jobtech", fetch)
