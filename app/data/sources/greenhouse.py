"""Greenhouse public board adapter.

Greenhouse exposes a free, public board API. Crucially, each job's `absolute_url` is the
**canonical apply URL** on the company's Greenhouse board — so this source also satisfies the
apply-link requirement (A5) with no extra resolution step. Docs:
https://developers.greenhouse.io/job-board.html
"""
from __future__ import annotations

from datetime import datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def fetch(board_token: str, company_name: str | None = None) -> list[RawPosting]:
    """Fetch all jobs for a Greenhouse board token, normalized to RawPosting.

    `company_name` is the display name; if omitted we fall back to the board token (the board
    metadata endpoint could supply the real name, but we keep this to a single request)."""
    data = fetch_json(API.format(token=board_token), params={"content": "true"})
    if not isinstance(data, dict) or "jobs" not in data:
        return []
    company = company_name or board_token
    out: list[RawPosting] = []
    for j in data.get("jobs") or []:
        url = j.get("absolute_url") or ""
        out.append(RawPosting(
            source_kind="ats_api",
            external_id=str(j.get("id", "")),
            title=j.get("title") or "",
            company=company,
            location=(j.get("location") or {}).get("name", "") or "",
            url=url,
            apply_url=url,                       # absolute_url IS the canonical apply URL
            description=html_to_text(j.get("content") or ""),
            posted_at=_parse_dt(j.get("updated_at")),
            raw=j,
        ))
    return out


register("greenhouse", fetch)
