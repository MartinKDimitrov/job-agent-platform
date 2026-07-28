"""Rabota.bg adapter — large Bulgarian job board (Retail, Production, Logistics, FMCG…), via its
official sitemap.

Like Zaplata.bg: robots.txt sets no Crawl-Delay and every job page embeds schema.org JobPosting
JSON-LD. The sitemap index (`/sitemap.xml`) fans out to `sitemaps/sitemap{1,2,3}.xml`, which mix
static pages with job ads; a job ad's URL is `/<category>/<YYYY>/<MM>/<DD>/<slug>.<id>`, so we keep
only those. Together with Zaplata this covers the non-IT Bulgarian employers that have no readable
careers page of their own.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text
from .jsonld import company_of, jobposting_ld, location_of, posted_of

SITEMAP_INDEX = "https://www.rabota.bg/sitemap.xml"
CRAWL_DELAY = 0.5  # robots.txt sets no Crawl-Delay; stay polite but not crippled

_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_OG_RE = r'property="{tag}" content="([^"]*)"'
# a job ad: /<category>/<YYYY>/<MM>/<DD>/<slug>.<numeric id>
_AD_URL_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/[^/]+\.\d+/?$")
_TITLE_TAIL_RE = re.compile(r"\s*[-–|]\s*(?:Rabota\.bg|rabota\.bg)\s*$", re.I)


def _locs_in(body: str) -> list[str]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    return [(u.findtext("sm:loc", namespaces=_SM_NS) or "").strip()
            for u in root.findall("sm:url", _SM_NS)]


def fetch_sitemap() -> list[tuple[str, str]]:
    """Resolve the sitemap index to its sub-sitemaps and return [(job_url, "")] for job ads only."""
    index = fetch_text(SITEMAP_INDEX)
    if not index:
        return []
    try:
        root = ET.fromstring(index)
    except ET.ParseError:
        return []
    subs = [(sm.findtext("sm:loc", namespaces=_SM_NS) or "").strip()
            for sm in root.findall("sm:sitemap", _SM_NS)]
    out: list[tuple[str, str]] = []
    for sm_url in [u for u in subs if u]:
        body = fetch_text(sm_url)
        if body:
            out.extend((loc, "") for loc in _locs_in(body) if loc and _AD_URL_RE.search(loc))
    return out


def _parse_job_page(url: str, html: str) -> RawPosting | None:
    ld = jobposting_ld(html)
    if ld:
        title = (ld.get("title") or "").strip()
        return RawPosting(
            source_kind="html", external_id=url, title=title, company=company_of(ld),
            location=location_of(ld), url=url, apply_url=url,
            description=html_to_text(ld.get("description") or ""), posted_at=posted_of(ld),
            raw={"ld": True},
        ) if title else None
    mt = re.search(_OG_RE.format(tag="og:title"), html)
    if not mt:
        return None
    title = _TITLE_TAIL_RE.sub("", mt.group(1)).strip()
    md = re.search(_OG_RE.format(tag="og:description"), html)
    return RawPosting(
        source_kind="html", external_id=url, title=title, company="",
        location="", url=url, apply_url=url,
        description=(md.group(1) if md else ""), raw={"ld": False},
    ) if title else None


def fetch(limit: int = 40, delay: float = CRAWL_DELAY,
          skip_urls: set[str] | frozenset = frozenset(),
          sleep=time.sleep) -> list[RawPosting]:
    """Fetch up to `limit` NEW job pages (not in `skip_urls`), pausing `delay` between fetches."""
    out: list[RawPosting] = []
    first = True
    for url, _lastmod in fetch_sitemap():
        if len(out) >= limit:
            break
        if url in skip_urls:
            continue
        if not first:
            sleep(delay)
        first = False
        html = fetch_text(url)
        if not html:
            continue
        rp = _parse_job_page(url, html)
        if rp:
            out.append(rp)
    return out


register("rabota", fetch)
