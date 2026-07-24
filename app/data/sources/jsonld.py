"""Shared schema.org JobPosting JSON-LD parsing — used by the JobTiger adapter and the
generic careers-page adapter (jsonld_careers). Kept tiny and dependency-free."""
from __future__ import annotations

import json
import re
from datetime import datetime

_LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def jobpostings_ld(html: str) -> list[dict]:
    """All JobPosting objects in the page's ld+json blocks (top-level, lists, or @graph)."""
    out: list[dict] = []
    for m in _LDJSON_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for it in items if isinstance(items, list) else [items]:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                out.append(it)
    return out


def jobposting_ld(html: str) -> dict | None:
    """First JobPosting in the page, or None (the common single-job-page case)."""
    found = jobpostings_ld(html)
    return found[0] if found else None


def location_of(ld: dict) -> str:
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


def posted_of(ld: dict) -> datetime | None:
    if not ld.get("datePosted"):
        return None
    try:
        return datetime.fromisoformat(str(ld["datePosted"]).replace("Z", "+00:00"))
    except ValueError:
        return None


def company_of(ld: dict) -> str:
    org = ld.get("hiringOrganization") or {}
    # a dict without a "name" key yields None here — guard BEFORE .strip() (operator
    # precedence made the trailing `or ""` bind only to the else branch)
    name = org.get("name") if isinstance(org, dict) else str(org)
    return (name or "").strip()
