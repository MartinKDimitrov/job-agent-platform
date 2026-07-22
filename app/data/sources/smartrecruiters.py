"""SmartRecruiters adapter (16в) — public Posting API, no key needed (verified live on Visa):

- LIST:   GET https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=N
          -> {"totalFound": N, "content": [{id, name, releasedDate, location{...}}]}
- DETAIL: GET .../postings/{id} -> postingUrl/applyUrl + jobAd.sections with SEPARATE
          companyDescription / jobDescription / qualifications / additionalInformation —
          so marketing and benefits never enter the posting text; qualifications get an
          explicit Requirements: header for the extractor.

One detail GET per posting -> max_jobs budget + politeness delay.
Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

import time
from datetime import datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

_LIST_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
_DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{pid}"
_DETAIL_DELAY = 0.3


def _location(item: dict) -> str:
    loc = item.get("location") or {}
    if loc.get("remote"):
        return "Remote"
    text = (loc.get("fullLocation") or "").strip()
    if not text:
        text = ", ".join(p for p in (loc.get("city"), str(loc.get("country") or "").upper()) if p)
    if loc.get("hybrid"):
        text = f"{text} (hybrid)" if text else "Hybrid"
    return text


def _posted(item: dict):
    raw = item.get("releasedDate") or ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None


def _description(slug: str, pid: str) -> tuple[str, str, str]:
    """(text, posting_url, apply_url) from the detail endpoint."""
    d = fetch_json(_DETAIL_URL.format(slug=slug, pid=pid))
    if not isinstance(d, dict):
        return "", "", ""
    sections = (d.get("jobAd") or {}).get("sections") or {}
    parts = []
    jd = (sections.get("jobDescription") or {}).get("text") or ""
    if jd:
        parts.append(html_to_text(jd))
    q = (sections.get("qualifications") or {}).get("text") or ""
    if q:
        parts.append("Requirements:\n" + html_to_text(q))
    return ("\n".join(parts), d.get("postingUrl") or "", d.get("applyUrl") or "")


def fetch(slug: str, company_name: str | None = None, max_jobs: int = 100,
          detail_delay: float = _DETAIL_DELAY) -> list[RawPosting]:
    out: list[RawPosting] = []
    offset = 0
    while len(out) < max_jobs:
        page = fetch_json(_LIST_URL.format(slug=slug),
                          params={"limit": 100, "offset": offset})
        if not isinstance(page, dict) or not page.get("content"):
            break
        for item in page["content"]:
            pid = str(item.get("id") or "")
            title = (item.get("name") or "").strip()
            if not (pid and title):
                continue
            if detail_delay and out:
                time.sleep(detail_delay)
            desc, url, apply_url = _description(slug, pid)
            url = url or f"https://jobs.smartrecruiters.com/{slug}/{pid}"
            out.append(RawPosting(
                source_kind="ats_api", external_id=pid, title=title,
                company=company_name or (item.get("company") or {}).get("name") or slug,
                location=_location(item), url=url, apply_url=apply_url or url,
                description=desc, posted_at=_posted(item),
                raw={"department": (item.get("department") or {}).get("label", "")},
            ))
            if len(out) >= max_jobs:
                break
        offset += len(page["content"])
        if offset >= int(page.get("totalFound") or 0):
            break
    return out


register("smartrecruiters", fetch)
