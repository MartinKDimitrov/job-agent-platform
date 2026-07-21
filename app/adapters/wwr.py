"""WeWorkRemotely adapter — global remote board via its public RSS feed.

`https://weworkremotely.com/remote-jobs.rss`. Item title is "Company: Role", <region> is the
location. source_kind="rss" (aggregator).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from .base import RawPosting, html_to_text, register
from .http import fetch_text

FEED_URL = "https://weworkremotely.com/remote-jobs.rss"


def _parse_feed(xml_text: str) -> list[RawPosting]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not raw_title or not link:
            continue
        company, sep, role = raw_title.partition(":")
        title = role.strip() if sep else raw_title
        company = company.strip() if sep else ""
        region = (item.findtext("region") or "").strip()
        posted = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                posted = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted = None
        out.append(RawPosting(
            source_kind="rss", external_id=link, title=title, company=company,
            location=region or "Remote", url=link, apply_url=link,
            description=html_to_text(item.findtext("description") or ""),
            posted_at=posted, raw={},
        ))
    return out


def fetch() -> list[RawPosting]:
    body = fetch_text(FEED_URL)
    return _parse_feed(body) if body else []


register("wwr", fetch)
