"""dev.bg adapter — the Bulgarian IT job board, via its official WordPress RSS job feed.

Verified live: `https://dev.bg/?feed=job_feed` (updated hourly) plus per-category variants
(`&job_category=<slug>`). Each item carries the full JD HTML in <content:encoded>. robots.txt
is open (blocks only one aggregator bot). The site times out plain bot UAs, so requests go
through fetch_text's browser-like headers. Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text

FEED_URL = "https://dev.bg/"
_NS = {"content": "http://purl.org/rss/1.0/modules/content/"}

# Category slugs on dev.bg (job_category query param). Configurable per call; this default set
# covers the broad engineering areas. Extend freely — each category is one extra feed request.
DEFAULT_CATEGORIES = [
    "back-end-development", "front-end-development", "full-stack-development",
    "mobile", "devops", "quality-assurance", "python",
]


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _company_from(link: str, guid: str) -> str:
    """dev.bg job links are /company/jobads/<company>-<role-slug>/ while the guid repeats only
    the role slug — the link slug's extra prefix is the company (verified on live items)."""
    ls, gs = _slug(link), _slug(guid)
    if gs and ls.endswith(gs) and len(ls) > len(gs):
        return ls[: -len(gs)].strip("-").replace("-", " ").title()
    return ""


def _parse_feed(xml_text: str) -> list[RawPosting]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not (link and title):
            continue
        content = item.findtext("content:encoded", namespaces=_NS) or ""
        desc = html_to_text(content) or html_to_text(item.findtext("description") or "")
        posted = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                posted = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        out.append(RawPosting(
            source_kind="rss", external_id=guid or link, title=title,
            company=_company_from(link, guid), location="",  # feed carries no location field
            url=link, apply_url=link, description=desc, posted_at=posted,
            raw={"guid": guid},
        ))
    return out


def fetch(categories: list[str] | None = None) -> list[RawPosting]:
    """Fetch the dev.bg job feed for each category (deduplicated by link across feeds)."""
    cats = DEFAULT_CATEGORIES if categories is None else categories
    seen: set[str] = set()
    out: list[RawPosting] = []
    for cat in cats or [None]:
        params = {"feed": "job_feed"}
        if cat:
            params["job_category"] = cat
        body = fetch_text(FEED_URL, params=params)
        if not body:
            continue
        for rp in _parse_feed(body):
            if rp.url not in seen:
                seen.add(rp.url)
                out.append(rp)
    return out


register("dev_bg", fetch)
