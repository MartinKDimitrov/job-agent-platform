"""d.vinci (dvinci-hr.com) — a German mid-market ATS. Third DE mid-market adapter (after rexx,
softgarden). Tenants live at {tenant}.dvinci-hr.com; the job LIST is server-rendered and every
job DETAIL embeds a schema.org JobPosting as JSON-LD — so we list the ids, then parse the
JSON-LD (via the shared jsonld helpers) for clean title/description/location/date.

- LIST:   GET {board}/de/jobs -> /de/jobs/{id}/{slug} links (present in server HTML).
- DETAIL: GET {board}/de/jobs/{id}/{slug} -> <script type="application/ld+json"> JobPosting.

`board` (the board id) = the tenant base URL https://{tenant}.dvinci-hr.com. Isolated per the
one-adapter rule; detail GETs paced.
"""
from __future__ import annotations

import re
import time

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text
from .jsonld import company_of, jobposting_ld, location_of, posted_of

DEFAULT_LIMIT = 30
DETAIL_DELAY = 0.2
_JOB_RE = re.compile(r"/(?:de|en)/jobs/(\d+)/[\w-]+")


def _detail(board: str, path: str, jid: str, company_name: str | None) -> RawPosting | None:
    html = fetch_text(f"{board}{path}")
    if not html:
        return None
    ld = jobposting_ld(html)
    if not ld:
        return None
    title = (ld.get("title") or "").strip()
    desc = html_to_text(ld.get("description") or "").strip()
    if not title or len(desc) < 40:
        return None
    url = f"{board}{path}"
    return RawPosting(
        source_kind="html", external_id=jid, title=title,
        company=company_name or company_of(ld), location=location_of(ld),
        url=url, apply_url=url, description=desc, posted_at=posted_of(ld),
        raw={"source": "dvinci", "base": board})


def fetch(board_url: str, company_name: str | None = None, limit: int = DEFAULT_LIMIT,
          delay: float = DETAIL_DELAY, sleep=time.sleep) -> list[RawPosting]:
    """board_url = the tenant base. One listing GET + paced detail GETs (JSON-LD per detail)."""
    board = (board_url or "").rstrip("/")
    if not board:
        return []
    listing = fetch_text(f"{board}/de/jobs") or fetch_text(f"{board}/en/jobs") or ""
    seen: set[str] = set()
    jobs: list[tuple[str, str]] = []                 # (path, id)
    for m in _JOB_RE.finditer(listing):
        jid = m.group(1)
        if jid in seen:
            continue
        seen.add(jid)
        jobs.append((m.group(0), jid))
        if len(jobs) >= limit:
            break
    out: list[RawPosting] = []
    for path, jid in jobs:
        rp = _detail(board, path, jid, company_name)
        if rp is not None:
            out.append(rp)
        sleep(delay)
    return out


register("dvinci", fetch)
