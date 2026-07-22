"""Teamtailor adapter (16в) — career sites (often on the company's OWN domain, e.g.
careers.mypos.com) built on Teamtailor expose a public RSS feed at `<site>/jobs.rss` with
full HTML descriptions, locations (tt: namespace) and a remoteStatus per posting.
Verified live on myPOS (robots.txt allows /jobs and declares Content-Signal search=yes).

The board identifier is the careers-site BASE URL for custom domains, or a bare slug for
`<slug>.teamtailor.com` hosted sites — `fetch` accepts both.
Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text

_TT_NS = {"tt": "https://teamtailor.com/locations"}


def base_url(slug_or_url: str) -> str:
    s = (slug_or_url or "").strip().rstrip("/")
    return s if s.startswith("http") else f"https://{s}.teamtailor.com"


def _location(item) -> str:
    remote = (item.findtext("remoteStatus") or "").strip().lower()
    if remote in ("fully", "fully_remote", "remote"):
        return "Remote"
    loc = item.find("tt:locations/tt:location", _TT_NS)
    parts = []
    if loc is not None:
        parts = [loc.findtext("tt:city", default="", namespaces=_TT_NS).strip(),
                 loc.findtext("tt:country", default="", namespaces=_TT_NS).strip()]
    text = ", ".join(p for p in parts if p)
    if remote == "hybrid":
        text = f"{text} (hybrid)" if text else "Hybrid"
    return text


def fetch(slug_or_url: str, company_name: str | None = None) -> list[RawPosting]:
    base = base_url(slug_or_url)
    body = fetch_text(f"{base}/jobs.rss")
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out: list[RawPosting] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not (title and link):
            continue
        guid = (item.findtext("guid") or "").strip()
        company = company_name or (item.findtext("company_name") or "").strip()
        posted = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                posted = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        out.append(RawPosting(
            source_kind="ats_api", external_id=guid or link, title=title,
            company=company, location=_location(item),
            url=link, apply_url=link, description=html_to_text(item.findtext("description") or ""),
            posted_at=posted, raw={"department": item.findtext("tt:department",
                                                               default="", namespaces=_TT_NS)},
        ))
    return out


register("teamtailor", fetch)
