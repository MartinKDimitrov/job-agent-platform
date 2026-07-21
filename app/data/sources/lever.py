"""Lever adapter — public postings API. hostedUrl/applyUrl are canonical apply URLs (A5).

`https://api.lever.co/v0/postings/{company}?mode=json` → list of postings with `text` (title),
`categories.location`, `descriptionPlain`, `createdAt` (epoch ms), `hostedUrl`, `applyUrl`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

API = "https://api.lever.co/v0/postings/{company}"


def _parse_ms(v):
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def fetch(company: str, company_name: str | None = None) -> list[RawPosting]:
    data = fetch_json(API.format(company=company), params={"mode": "json"}, browser=True)
    if not isinstance(data, list):
        return []
    name = company_name or company
    out = []
    for j in data:
        cats = j.get("categories") or {}
        url = j.get("hostedUrl") or ""
        out.append(RawPosting(
            source_kind="ats_api", external_id=str(j.get("id", "")),
            title=j.get("text") or "", company=name, location=cats.get("location") or "",
            url=url, apply_url=j.get("applyUrl") or url,
            description=j.get("descriptionPlain") or html_to_text(j.get("description") or ""),
            posted_at=_parse_ms(j.get("createdAt")), raw=j,
        ))
    return out


register("lever", fetch)
