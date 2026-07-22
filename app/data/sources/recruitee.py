"""Recruitee adapter (16в) — public careers API, one request per company (verified live
on sendcloud): GET https://{slug}.recruitee.com/api/offers/ -> {"offers": [...]} where each
offer carries SEPARATE description/requirements HTML, careers_url + careers_apply_url,
a human location string and a remote flag. No per-job detail requests needed.
Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

from datetime import datetime

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_json

_URL = "https://{slug}.recruitee.com/api/offers/"


def _posted(offer: dict):
    raw = (offer.get("created_at") or "").replace(" UTC", "")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _location(offer: dict) -> str:
    if offer.get("remote"):
        return "Remote"
    text = (offer.get("location") or "").strip()
    if not text:
        text = ", ".join(p for p in (offer.get("city"), offer.get("country")) if p)
    if offer.get("hybrid"):
        text = f"{text} (hybrid)" if text else "Hybrid"
    return text


def fetch(slug: str, company_name: str | None = None, max_jobs: int = 100) -> list[RawPosting]:
    data = fetch_json(_URL.format(slug=slug), browser=True)
    if not isinstance(data, dict):
        return []
    out: list[RawPosting] = []
    for offer in data.get("offers") or []:
        title = (offer.get("title") or "").strip()
        url = (offer.get("careers_url") or "").strip()
        if not (title and url):
            continue
        parts = []
        if offer.get("description"):
            parts.append(html_to_text(offer["description"]))
        if offer.get("requirements"):
            parts.append("Requirements:\n" + html_to_text(offer["requirements"]))
        out.append(RawPosting(
            source_kind="ats_api", external_id=str(offer.get("id") or url), title=title,
            company=company_name or (offer.get("company_name") or "").strip() or slug,
            location=_location(offer), url=url,
            apply_url=(offer.get("careers_apply_url") or url),
            description="\n".join(parts), posted_at=_posted(offer),
            raw={"department": offer.get("department") or ""},
        ))
        if len(out) >= max_jobs:
            break
    return out


register("recruitee", fetch)
