"""Ashby adapter — public job-board API. jobUrl/applyUrl are canonical apply URLs (A5).

`https://api.ashbyhq.com/posting-api/job-board/{board}` → {"jobs": [...]} with `title`,
`location`, `isRemote`, `publishedAt` (ISO), `jobUrl`, `applyUrl`, `descriptionPlain`.
"""
from __future__ import annotations

from datetime import datetime

from .base import RawPosting, html_to_text, register
from .http import fetch_json

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def _parse_iso(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def fetch(board: str, company_name: str | None = None) -> list[RawPosting]:
    data = fetch_json(API.format(board=board), browser=True)
    if not isinstance(data, dict):
        return []
    name = company_name or board
    out = []
    for j in data.get("jobs") or []:
        url = j.get("jobUrl") or ""
        location = j.get("location") or ""
        if j.get("isRemote") and "remote" not in location.lower():
            location = (location + " · Remote").strip(" ·")
        out.append(RawPosting(
            source_kind="ats_api", external_id=str(j.get("id", "")),
            title=j.get("title") or "", company=name, location=location,
            url=url, apply_url=j.get("applyUrl") or url,
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or ""),
            posted_at=_parse_iso(j.get("publishedAt")), raw=j,
        ))
    return out


register("ashby", fetch)
