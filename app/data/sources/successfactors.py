"""SAP SuccessFactors adapter — the OTHER enterprise ATS behind SAP itself and many DAX/CAC/
FTSE giants that aren't on Workday. Second enterprise adapter (Workday was first).

SuccessFactors "Career Site Builder" (CSB) sites have no JSON API and no JSON-LD (verified
live on jobs.sap.com 2026-07-24) — they render server-side HTML:
- LIST:   GET {base}/tile-search-results/?q=&startrow=N  -> <li class="job-tile" data-url=
          "/job/{slug}/{id}/"> tiles (standard across CSB tenants).
- DETAIL: GET {base}{data-url} -> job page; title in <h1>/itemprop=title, body in
          <span class="jobdescription"> (nested markup -> generous window + html_to_text).

`base` = the CSB host (e.g. https://jobs.sap.com), stored as the board id. Per-tenant CSB
theming varies, so extraction is deliberately tolerant (the requirement extractor already
filters noise). Detail GETs paced. Isolated per the one-adapter rule.
"""
from __future__ import annotations

import re
import time

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text

DEFAULT_LIMIT = 20
DETAIL_DELAY = 0.2

_TILE_RE = re.compile(r'<li class="job-tile[^"]*"[^>]*data-url="(/job/[^"]+)"', re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_TITLE_PROP_RE = re.compile(r'itemprop="title"[^>]*>(.*?)</', re.S | re.I)
_DESC_RE = re.compile(r'class="jobdescription"[^>]*>(.*)', re.S | re.I)
# footers that mark the end of the real description across CSB tenants
_DESC_END_RE = re.compile(r"(Job Segment:|Requisition ID:|Nearest Major Market|"
                          r"</footer>|class=\"job-)", re.I)


def _clean(html_fragment: str) -> str:
    return html_to_text(html_fragment or "").strip()


def _detail(base: str, path: str) -> RawPosting | None:
    html = fetch_text(f"{base}{path}")
    if not html:
        return None
    tm = _TITLE_PROP_RE.search(html) or _H1_RE.search(html)
    title = _clean(tm.group(1)) if tm else ""
    if not title:
        return None
    dm = _DESC_RE.search(html)
    desc = ""
    if dm:
        window = dm.group(1)[:25000]
        end = _DESC_END_RE.search(window)
        if end:
            window = window[:end.start()]
        desc = _clean(window)
    if len(desc) < 40:
        return None                         # no usable description -> can't score
    url = f"{base}{path}"
    jid = path.rstrip("/").rsplit("/", 1)[-1]
    return RawPosting(
        source_kind="html", external_id=jid, title=title, company="",
        location="", url=url, apply_url=url, description=desc,
        raw={"source": "successfactors", "base": base},
    )


def fetch(base_url: str, company_name: str | None = None, limit: int = DEFAULT_LIMIT,
          delay: float = DETAIL_DELAY, sleep=time.sleep) -> list[RawPosting]:
    """base_url = the CSB host. One listing GET + paced detail GETs."""
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    listing = fetch_text(f"{base}/tile-search-results/?q=") or ""
    paths = list(dict.fromkeys(_TILE_RE.findall(listing)))[:limit]
    out: list[RawPosting] = []
    for path in paths:
        rp = _detail(base, path.replace("&amp;", "&"))
        if rp is not None:
            rp.company = company_name or ""
            out.append(rp)
        sleep(delay)
    return out


register("successfactors", fetch)
