"""rexx systems adapter — a German mid-market ATS (rexx-recruitment.com) that many DE
Mittelstand employers run and that our US-centric adapters all missed. First of the German
mid-market adapters (measurement: Preh and others resolve here once careers discovery works).

rexx boards are SERVER-RENDERED HTML (no JSON API, no JSON-LD) — good for us, no SPA problem:
- LIST:   GET {list_url} -> <a href="…?yid={id}">{title}</a> anchors. Same content whether
          the URL is the tenant portal ({tenant}-portal.rexx-recruitment.com/stellenangebote
          .html) or the company-hosted mirror (career.{domain}/…/aktuelle-stellenangebote.html).
- DETAIL: GET {…?yid=id} -> <h1> title, <title>…bei {company}</title>, and the job body in
          <div id="main_content"> … <div class="rexx_footer"> (scheme-task/-profile/-benefits).

`list_url` (the board id) is a full list URL — detail links in the list are absolute, so a
single list GET + paced detail GETs is enough. Isolated per the one-adapter rule.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urldefrag

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text

DEFAULT_LIMIT = 25
DETAIL_DELAY = 0.2

# list anchors carry the job id in ?yid=N (DE: aktuelle-stellenangebote, EN: current-job-offers)
_JOB_RE = re.compile(r'<a[^>]+href="([^"]*[?&]yid=(\d+)[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_TITLE_COMPANY_RE = re.compile(r"<title>[^<]*?\bbei\s+([^<]+?)\s*</title>", re.I)
_META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.I)
# the job body: from the main content container down to the rexx footer
_MAIN_RE = re.compile(r'id="main_content"(.*?)(?:class="rexx_footer"|</body>)', re.S | re.I)
_LOC_RE = re.compile(r"\bin\s+(.+?)\s*\(", re.I)   # meta desc "… in {city} ({country})"


def _clean(fragment: str) -> str:
    return html_to_text(fragment or "").strip()


def _detail(url: str, company_name: str | None, yid: str) -> RawPosting | None:
    html = fetch_text(url)
    if not html:
        return None
    tm = _H1_RE.search(html)
    title = _clean(tm.group(1)) if tm else ""
    if not title:
        return None
    mm = _MAIN_RE.search(html)
    desc = _clean(mm.group(1)[:25000]) if mm else ""
    if len(desc) < 40:
        return None                          # no usable description -> can't score
    company = company_name or ""
    if not company:
        cm = _TITLE_COMPANY_RE.search(html)
        company = _clean(cm.group(1)) if cm else ""
    location = ""
    dm = _META_DESC_RE.search(html)
    if dm:
        lm = _LOC_RE.search(dm.group(1))
        if lm:
            location = lm.group(1).strip()
    return RawPosting(
        source_kind="html", external_id=yid, title=title, company=company,
        location=location, url=url, apply_url=url, description=desc,
        raw={"source": "rexx", "base": url},
    )


def fetch(list_url: str, company_name: str | None = None, limit: int = DEFAULT_LIMIT,
          delay: float = DETAIL_DELAY, sleep=time.sleep) -> list[RawPosting]:
    """list_url = a rexx joblist URL (tenant portal or company mirror). One listing GET +
    paced detail GETs. Detail links in the listing are absolute."""
    list_url = (list_url or "").strip()
    if not list_url:
        return []
    listing = fetch_text(list_url) or ""
    seen: set[str] = set()
    jobs: list[tuple[str, str]] = []           # (detail_url, yid)
    for href, yid, _title in _JOB_RE.findall(listing):
        if yid in seen:
            continue
        seen.add(yid)
        jobs.append((urldefrag(href.replace("&amp;", "&"))[0], yid))
        if len(jobs) >= limit:
            break
    out: list[RawPosting] = []
    for url, yid in jobs:
        rp = _detail(url, company_name, yid)
        if rp is not None:
            out.append(rp)
        sleep(delay)
    return out


register("rexx", fetch)
