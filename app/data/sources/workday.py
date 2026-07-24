"""Workday adapter — the enterprise ATS that hosts a large share of the DAX/CAC/FTSE/IBEX
giants (the >=1000-per-large-economy plan's real backbone; corporate "careers pages" of big
firms are almost always a Workday or SuccessFactors board, not a scrapeable HTML page).

Workday exposes a public "CXS" JSON API per career site — no key:
- LIST:   POST {base}/jobs            body {"limit","offset","searchText","appliedFacets":{}}
          -> {"total", "jobPostings":[{title, externalPath, locationsText, bulletFields}]}
- DETAIL: GET  {base}{externalPath}   -> {"jobPostingInfo":{jobDescription(HTML), location,
          externalUrl, startDate, country, jobReqId, canApply}}

`base` = https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site} — stored whole as the
board id (ats_slug), because a Workday board needs three parts (tenant, datacenter wdN, site),
not a single slug. Detection discovers it by scanning the company's careers page for the
myworkdayjobs host (see ats_detect). Verified live 2026-07-24 against nvidia.wd5.

Detail GETs are paced like the other detail-heavy adapters. Isolated per the one-adapter rule.
"""
from __future__ import annotations

import time
from datetime import datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json, post_json

DEFAULT_LIMIT = 20          # postings per board per cycle (paced detail GETs after)
DETAIL_DELAY = 0.15


def _location(hit_loc: str) -> str:
    return hit_loc or ""


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def fetch(base_url: str, company_name: str | None = None, limit: int = DEFAULT_LIMIT,
          delay: float = DETAIL_DELAY, sleep=time.sleep) -> list[RawPosting]:
    """base_url = the CXS base (…/wday/cxs/{tenant}/{site}). One list POST + paced detail GETs."""
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    listing = post_json(f"{base}/jobs",
                        {"appliedFacets": {}, "limit": limit, "offset": 0, "searchText": ""})
    if not isinstance(listing, dict):
        return []
    company = company_name or ""
    out: list[RawPosting] = []
    for jp in listing.get("jobPostings") or []:
        path = jp.get("externalPath") or ""
        if not path:
            continue
        det = fetch_json(f"{base}{path}")
        info = (det or {}).get("jobPostingInfo") or {}
        desc = html_to_text(info.get("jobDescription") or "")
        if not desc:
            continue                 # no text -> can't score -> skip
        url = info.get("externalUrl") or f"{base}{path}"
        out.append(RawPosting(
            source_kind="ats_api",
            external_id=str(info.get("jobReqId") or jp.get("bulletFields", [""])[0] or path),
            title=info.get("title") or jp.get("title") or "",
            company=company,
            location=_location(info.get("location") or jp.get("locationsText") or ""),
            url=url,
            apply_url=url,
            description=desc,
            posted_at=_parse_dt(info.get("startDate")),
            raw={"source": "workday", "base": base},
        ))
        sleep(delay)
    return out


register("workday", fetch)
