"""Zaplata.bg adapter — broad Bulgarian job board (Retail, Logistics, Manufacturing, FMCG…),
via its official sitemap.

Verified live: robots.txt permits job pages (only /search/ and account paths are disallowed) and
sets NO Crawl-Delay, so — unlike JobTiger's 30s — we can pull at a normal, polite pace. The sitemap
index (`/sitemap.xml`) points to `sitemap-ads-*.xml`, which list the individual job pages; each job
page embeds schema.org JobPosting JSON-LD, so parsing is structured (og:-meta as a fallback).

This is the biggest directly-readable source of NON-IT Bulgarian jobs — exactly the sectors the
company-registry careers-page discovery misses (they post here, not on their own sites).
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text
from .jsonld import company_of, jobposting_ld, location_of, posted_of

SITEMAP_INDEX = "https://www.zaplata.bg/sitemap.xml"
CRAWL_DELAY = 0.5  # robots.txt sets no Crawl-Delay; stay polite but not crippled

_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_OG_RE = r'property="{tag}" content="([^"]*)"'
_TITLE_TAIL_RE = re.compile(r"\s*[-–]\s*обява за работа в Zaplata\.bg\s*$", re.I)


def _urls_in(body: str) -> list[tuple[str, str]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for url_el in root.findall("sm:url", _SM_NS):
        loc = (url_el.findtext("sm:loc", namespaces=_SM_NS) or "").strip()
        lastmod = (url_el.findtext("sm:lastmod", namespaces=_SM_NS) or "").strip()
        if loc:
            out.append((loc, lastmod))
    return out


def fetch_sitemap() -> list[tuple[str, str]]:
    """Resolve the sitemap index to the ad sub-sitemaps and return [(job_url, lastmod)]."""
    index = fetch_text(SITEMAP_INDEX)
    if not index:
        return []
    try:
        root = ET.fromstring(index)
    except ET.ParseError:
        return []
    ad_maps = [(sm.findtext("sm:loc", namespaces=_SM_NS) or "").strip()
               for sm in root.findall("sm:sitemap", _SM_NS)]
    ad_maps = [u for u in ad_maps if u and "sitemap-ads" in u]
    out: list[tuple[str, str]] = []
    for sm_url in ad_maps:
        body = fetch_text(sm_url)
        if body:
            out.extend(_urls_in(body))
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
    # fallback: og:title ("… - обява за работа в Zaplata.bg")
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
    """Fetch up to `limit` NEW job pages (not in `skip_urls`), pausing `delay` between fetches.
    Pass the DB's already-known URLs as skip_urls so the budget is spent only on new postings."""
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


register("zaplata", fetch)
