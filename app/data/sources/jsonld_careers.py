"""Generic careers-page adapter (16в, final piece) — for companies WITHOUT a supported ATS
but WITH a careers page that publishes schema.org JobPosting JSON-LD (banks, telecoms,
retail... — the discovery table's "careers ✓, ATS —" group).

Flow per company:
1. robots.txt check for the careers URL (cached per host; unreachable robots = allowed,
   per the standard). Disallowed -> we simply don't crawl that company.
2. The careers page itself may embed JobPosting objects (list pages) — taken directly.
3. Otherwise job-looking links on the page (same site only) are fetched politely
   (`delay` apart, `max_jobs` budget) and each page's JobPosting JSON-LD is parsed.

SPA-rendered pages yield nothing here — the probe tool simply never activates those
companies. Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text
from .jsonld import company_of, jobpostings_ld, location_of, posted_of

_JOB_HREF_RE = re.compile(
    r"""href=["']([^"'#]*(?:/job[s]?/|/career[s]?/|/position|vacanc|jobad|obiava|
    jobId=|job_id=|/j/)[^"'#]*)["']""", re.I | re.X)
_ASSET_RE = re.compile(r"\.(css|js|png|jpe?g|svg|woff2?|ico|pdf|xml)(\?|$)", re.I)

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _allowed(url: str) -> bool:
    host = urlparse(url).netloc
    if host not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        body = fetch_text(f"{urlparse(url).scheme}://{host}/robots.txt")
        if body is None:
            _robots_cache[host] = None            # unreachable robots -> allowed
        else:
            rp.parse(body.splitlines())
            _robots_cache[host] = rp
    rp = _robots_cache[host]
    return True if rp is None else rp.can_fetch("*", url)


def _same_site(careers_url: str, link: str) -> bool:
    a, b = urlparse(careers_url).netloc, urlparse(link).netloc
    strip = lambda h: ".".join(h.split(".")[-2:])          # noqa: E731 — registrable domain
    return bool(b) and (a == b or strip(a) == strip(b))


def _to_posting(ld: dict, url: str, company_name: str | None) -> RawPosting | None:
    title = (ld.get("title") or "").strip()
    if not title:
        return None
    return RawPosting(
        source_kind="html", external_id=str(ld.get("url") or url), title=title,
        company=(company_of(ld) or company_name or "").strip(),
        location=location_of(ld), url=str(ld.get("url") or url), apply_url=str(ld.get("url") or url),
        description=html_to_text(ld.get("description") or ""), posted_at=posted_of(ld),
        raw={"generic_jsonld": True},
    )


def fetch(careers_url: str, company_name: str | None = None, max_jobs: int = 30,
          delay: float = 0.5, sleep=time.sleep) -> list[RawPosting]:
    careers_url = (careers_url or "").strip()
    if not careers_url or not _allowed(careers_url):
        return []
    html = fetch_text(careers_url)
    if not html:
        return []
    out: list[RawPosting] = []
    seen: set[str] = set()

    # list pages that embed the postings directly
    for ld in jobpostings_ld(html):
        rp = _to_posting(ld, careers_url, company_name)
        if rp and rp.url not in seen:
            seen.add(rp.url)
            out.append(rp)
            if len(out) >= max_jobs:
                return out

    # otherwise follow job-looking links, politely
    links = []
    for m in _JOB_HREF_RE.finditer(html):
        link = urljoin(careers_url + "/", m.group(1))
        if (_ASSET_RE.search(link) or link.rstrip("/") == careers_url.rstrip("/")
                or not _same_site(careers_url, link) or link in seen):
            continue
        if link not in links:
            links.append(link)
    for link in links[:max_jobs]:
        if len(out) >= max_jobs:
            break
        if not _allowed(link):
            continue
        if out or links.index(link) > 0:
            sleep(delay)
        page = fetch_text(link)
        if not page:
            continue
        for ld in jobpostings_ld(page):
            rp = _to_posting(ld, link, company_name)
            if rp and rp.url not in seen:
                seen.add(rp.url)
                out.append(rp)
    return out


register("jsonld", fetch)
