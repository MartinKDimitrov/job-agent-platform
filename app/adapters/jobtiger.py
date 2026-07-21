"""JobTiger.bg adapter — broad Bulgarian job board (all professions), via its official sitemap.

Verified live: robots.txt is `Allow: /` (job pages under /obiavi-za-rabota/ are permitted; only
keyword-search URLs are disallowed), publishes `sitemap_jobs_0.xml`, and sets an explicit
`ClaudeBot Crawl-Delay: 30` — i.e. bots are accommodated with politeness. We honour that: at
most `limit` new pages per run, sleeping `delay` seconds between page fetches, and skipping
already-known URLs BEFORE fetching. Job pages embed schema.org JobPosting JSON-LD (in @graph),
so parsing is structured, with og:-meta as fallback. Designed for the daily background job, not
the interactive "Search now" (the crawl delay makes it slow by design).
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from .base import RawPosting, html_to_text, register
from .http import fetch_text

SITEMAP_URL = "https://www.jobtiger.bg/sitemaps/sitemap_jobs_0.xml"
CRAWL_DELAY = 30.0  # per robots.txt ClaudeBot Crawl-Delay

_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_LDJSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_OG_RE = r'property="{tag}" content="([^"]*)"'


def fetch_sitemap() -> list[tuple[str, str]]:
    """Return [(job_url, lastmod)] from the official jobs sitemap (newest data first there)."""
    body = fetch_text(SITEMAP_URL)
    if not body:
        return []
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


def _jobposting_ld(html: str) -> dict | None:
    for m in _LDJSON_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for it in items if isinstance(items, list) else [items]:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return None


def _location_of(ld: dict) -> str:
    loc = ld.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            locality = str(addr.get("addressLocality") or "")
            country = str(addr.get("addressCountry") or "")
            # some pages already end the locality with the country ("Plovdiv, Bulgaria")
            if country and country.lower() not in locality.lower():
                return ", ".join(p for p in (locality, country) if p)
            return locality
    return ""


def _parse_job_page(url: str, html: str) -> RawPosting | None:
    ld = _jobposting_ld(html)
    if ld:
        title = (ld.get("title") or "").strip()
        org = ld.get("hiringOrganization") or {}
        company = (org.get("name") if isinstance(org, dict) else str(org) or "").strip()
        posted = None
        if ld.get("datePosted"):
            try:
                posted = datetime.fromisoformat(str(ld["datePosted"]).replace("Z", "+00:00"))
            except ValueError:
                posted = None
        rp = RawPosting(
            source_kind="html", external_id=url, title=title, company=company,
            location=_location_of(ld), url=url, apply_url=url,
            description=html_to_text(ld.get("description") or ""), posted_at=posted,
            raw={"ld": True},
        )
        return rp if rp.title else None
    # fallback: og: meta ("IRC97994 - Senior Technician - Обява за работа в JobTiger")
    mt = re.search(_OG_RE.format(tag="og:title"), html)
    md = re.search(_OG_RE.format(tag="og:description"), html)
    if not mt:
        return None
    title = re.sub(r"\s*-\s*Обява за работа в JobTiger\s*$", "", mt.group(1)).strip()
    desc = md.group(1) if md else ""
    comp = re.search(r"Фирма:\s*([^;]+);", desc)
    loc = re.search(r"Местоположение:\s*([^;]+);", desc)
    return RawPosting(
        source_kind="html", external_id=url, title=title,
        company=(comp.group(1).strip() if comp else ""),
        location=(loc.group(1).strip() if loc else ""),
        url=url, apply_url=url, description=desc, raw={"ld": False},
    ) if title else None


def fetch(limit: int = 20, delay: float = CRAWL_DELAY,
          skip_urls: set[str] | frozenset = frozenset(),
          sleep=time.sleep) -> list[RawPosting]:
    """Fetch up to `limit` NEW job pages (not in `skip_urls`), honouring the crawl delay
    between page requests. Pass the DB's already-known URLs as skip_urls so the delay budget
    is spent only on genuinely new postings."""
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


register("jobtiger", fetch)
