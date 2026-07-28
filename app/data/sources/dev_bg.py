"""dev.bg adapter — the Bulgarian IT job board, via its WordPress RSS feeds.

Two complementary feeds (both verified live, 2026-07):
- GLOBAL recency: `/?feed=job_feed&paged=N` — the newest postings site-wide, ~10 per page,
  ~50 postings/day. The category parameter is IGNORED by the server (verified: identical items
  for every category), so per-category feeds are useless — pagination is the coverage.
- TARGETED search: `/?s=<term>&post_type=job_listing&feed=rss2&paged=N` — real search results
  (e.g. 'android' returns exactly the 45 postings the site UI shows), full JD in
  content:encoded. This reaches profile-relevant postings posted weeks ago, far beyond the
  global-feed window.

The site times out plain bot UAs, so requests go through fetch_text's browser-like headers.
Isolated per the one-adapter-per-source rule.
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

DEFAULT_PAGES = 3          # global feed: 3 pages ≈ the ~30 newest postings
DEFAULT_SEARCH_PAGES = 5   # per search term: up to ~50 matching postings


# dev.bg's RSS carries no location, but the job PAGE shows a city badge (the JSON-LD address is
# left empty). Read it from the badge div, or the map-pin image's alt text as a fallback.
_LOC_BADGE = re.compile(r'job-card-badge location"[^>]*>\s*<img[^>]*>\s*([^<]+?)\s*</div>', re.I | re.S)
_PIN_ALT = re.compile(r'pin\.png"[^>]*alt="([^"-]+?)\s*-', re.I)


def location_from_page(html: str) -> str:
    """The city shown on a dev.bg job page ('София', 'Пловдив', 'Remote'…), '' if none found."""
    for rx in (_LOC_BADGE, _PIN_ALT):
        m = rx.search(html or "")
        if m:
            loc = re.sub(r"\s+", " ", m.group(1)).strip()
            if loc and loc.lower() != "a pin icon":
                return loc
    return ""


def fetch_location(url: str) -> str:
    """Fetch a dev.bg job page and return its city badge (used to backfill the empty RSS location)."""
    return location_from_page(fetch_text(url) or "")


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _company_from(link: str, guid: str, title: str = "") -> str:
    """dev.bg job links are /company/jobads/<company>-<role-slug>/ while the guid repeats only
    the role slug — the link slug's extra prefix is the company (verified on live items).
    The SEARCH feed's guid is a WordPress `?p=N` permalink (no slug), so fall back to the
    TITLE: strip the title's words off the link slug's tail; what remains is the company
    (this filled the empty-company cards from targeted dev.bg results). Reposted ads get a
    numeric slug suffix, stacking on each repost ('...-developer-1-1-1') — both variants
    are tried."""
    gs, ts = _slug(guid), _slugify(title)
    raw = _slug(link)
    for ls in dict.fromkeys((raw, re.sub(r"(-\d+)+$", "", raw))):
        if gs and ls.endswith(gs) and len(ls) > len(gs):
            return ls[: -len(gs)].strip("-").replace("-", " ").title()
        if ts and ls.endswith(ts) and len(ls) > len(ts):
            return ls[: -len(ts)].strip("-").replace("-", " ").title()
        title_words = set(ts.split("-")) if ts else set()
        toks = ls.split("-")
        i = len(toks)
        while i > 0 and toks[i - 1] in title_words:
            i -= 1
        if 0 < i < len(toks):
            return " ".join(toks[:i]).title()
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
            company=_company_from(link, guid, title), location="",  # feed has no location field
            url=link, apply_url=link, description=desc, posted_at=posted,
            raw={"guid": guid},
        ))
    return out


def _fetch_pages(base_params: dict, pages: int) -> list[RawPosting]:
    out: list[RawPosting] = []
    for page in range(1, pages + 1):
        params = dict(base_params)
        if page > 1:
            params["paged"] = page
        body = fetch_text(FEED_URL, params=params)
        if not body:
            break
        batch = _parse_feed(body)
        if not batch:
            break
        out.extend(batch)
    return out


def fetch(search_terms: list[str] | None = None, pages: int = DEFAULT_PAGES,
          search_pages: int = DEFAULT_SEARCH_PAGES) -> list[RawPosting]:
    """Global newest postings + (optionally) targeted search per term, deduplicated by link."""
    seen: set[str] = set()
    out: list[RawPosting] = []

    def add(batch: list[RawPosting]) -> None:
        for rp in batch:
            if rp.url not in seen:
                seen.add(rp.url)
                out.append(rp)

    add(_fetch_pages({"feed": "job_feed"}, pages))
    for term in search_terms or []:
        add(_fetch_pages({"s": term, "post_type": "job_listing", "feed": "rss2"}, search_pages))
    return out


register("dev_bg", fetch)
