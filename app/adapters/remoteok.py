"""RemoteOK adapter — global remote job board with a public JSON API.

`https://remoteok.com/api` returns a JSON array whose FIRST element is a legal/attribution
notice (skipped). Jobs are global-remote, so they pass the location hard filter for remote
candidates and broaden coverage well beyond the seed ATS boards. source_kind="rss" (aggregator,
not canonical), so dedup won't upgrade apply URLs to it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .base import RawPosting, html_to_text, register
from .http import fetch_json

API = "https://remoteok.com/api"


def _parse_epoch(v):
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def fetch() -> list[RawPosting]:
    data = fetch_json(API, browser=True)
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        if not isinstance(j, dict) or "legal" in j or not j.get("position"):
            continue
        url = j.get("url") or j.get("apply_url") or ""
        out.append(RawPosting(
            source_kind="rss", external_id=str(j.get("id", "")),
            title=j.get("position") or "", company=j.get("company") or "",
            location=j.get("location") or "Remote", url=url,
            apply_url=j.get("apply_url") or url,
            description=html_to_text(j.get("description") or ""),
            posted_at=_parse_epoch(j.get("epoch")), raw=j,
        ))
    return out


register("remoteok", fetch)
