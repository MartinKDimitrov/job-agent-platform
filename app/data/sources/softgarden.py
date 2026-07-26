"""softgarden adapter — the German mid-market ATS market leader (verified live: it dominates
DE Mittelstand careers pages). Second German mid-market adapter after rexx.

softgarden tenants live at {tenant}.career.softgarden.de and expose a PUBLIC schema.org JSON
DataFeed — the cleanest kind of source, and the whole job description ships in the feed, so no
per-job detail GETs are needed:
- FEED: GET {board}/jobs.feed.json -> {"dataFeedElement": [{"item": {JobPosting}}, …]}
        JobPosting: title, url, description (HTML), datePosted, identifier{name(company), value(id)},
        jobLocation.address.addressLocality.

`board` (the board id) = the tenant base URL, e.g. https://beinbauer-group.career.softgarden.de.
Isolated per the one-adapter rule.
"""
from __future__ import annotations

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

DEFAULT_LIMIT = 100
FEED_PATH = "/jobs.feed.json"


def _location(item: dict) -> str:
    loc = item.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            return (addr.get("addressLocality") or addr.get("addressRegion")
                    or addr.get("addressCountry") or "").strip()
    return ""


def _company(item: dict, fallback: str) -> str:
    ident = item.get("identifier")
    if isinstance(ident, dict) and ident.get("name"):
        return str(ident["name"]).strip()
    org = item.get("hiringOrganization")
    if isinstance(org, dict) and org.get("name"):
        return str(org["name"]).strip()
    return fallback or ""


def _job_id(item: dict) -> str:
    ident = item.get("identifier")
    if isinstance(ident, dict) and ident.get("value") is not None:
        return str(ident["value"])
    url = item.get("url") or ""
    return url.rstrip("/").rsplit("/", 2)[-2] if "/jobs/" in url else url


def fetch(board_url: str, company_name: str | None = None,
          limit: int = DEFAULT_LIMIT) -> list[RawPosting]:
    """board_url = the tenant base URL. One JSON GET; descriptions ship in the feed."""
    board = (board_url or "").rstrip("/")
    if not board:
        return []
    feed = fetch_json(f"{board}{FEED_PATH}", browser=True)
    elements = feed.get("dataFeedElement") if isinstance(feed, dict) else None
    if not isinstance(elements, list):
        return []
    out: list[RawPosting] = []
    for el in elements[:limit]:
        item = el.get("item") if isinstance(el, dict) else None
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        desc = html_to_text(item.get("description") or "").strip()
        if not (title and url) or len(desc) < 40:
            continue                              # need a scoreable description
        out.append(RawPosting(
            source_kind="json", external_id=_job_id(item), title=title,
            company=_company(item, company_name or ""), location=_location(item),
            url=url, apply_url=url, description=desc,
            raw={"source": "softgarden", "base": board},
        ))
    return out


register("softgarden", fetch)
