"""Personio adapter (16в) — public careers XML feed (verified live), popular with EU/DACH
employers: GET https://{slug}.jobs.personio.de/xml (or .com) ->
<workzag-jobs><position> with id / name / office / jobDescriptions (named HTML sections).
One request per company; job URL is https://{slug}.jobs.personio.{tld}/job/{id}.
Section names become plain-text headers so the requirement extractor can bucket them.
Isolated per the one-adapter-per-source rule.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ...domain.entities import RawPosting
from ...domain.text import html_to_text
from .base import register
from .http import fetch_text

_TLDS = ("de", "com")


def _descriptions(pos) -> str:
    parts = []
    for d in pos.findall("./jobDescriptions/jobDescription"):
        name = (d.findtext("name") or "").strip()
        value = html_to_text(d.findtext("value") or "")
        if value:
            parts.append(f"{name}:\n{value}" if name else value)
    return "\n".join(parts)


def fetch(slug: str, company_name: str | None = None, max_jobs: int = 100) -> list[RawPosting]:
    for tld in _TLDS:
        base = f"https://{slug}.jobs.personio.{tld}"
        body = fetch_text(f"{base}/xml")
        if not body:
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            continue
        out: list[RawPosting] = []
        for pos in root.iter("position"):
            pid = (pos.findtext("id") or "").strip()
            title = (pos.findtext("name") or "").strip()
            if not (pid and title):
                continue
            url = f"{base}/job/{pid}"
            out.append(RawPosting(
                source_kind="ats_api", external_id=pid, title=title,
                company=company_name or slug, location=(pos.findtext("office") or "").strip(),
                url=url, apply_url=url, description=_descriptions(pos),
                raw={"category": (pos.findtext("recruitingCategory") or "").strip()},
            ))
            if len(out) >= max_jobs:
                break
        if out or root.tag == "workzag-jobs":     # valid (possibly empty) feed found
            return out
    return []


register("personio", fetch)
