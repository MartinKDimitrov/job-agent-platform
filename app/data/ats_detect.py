"""ATS auto-detection (ROADMAP 16б): given a company name (and optionally its careers page),
find which supported ATS hosts its postings and under what slug.

Two complementary strategies, both cheap and polite (a handful of GETs per company):
1. SLUG PROBING — guess likely board slugs from the name and hit each ATS's public JSON
   endpoint. A valid board answers 200 with a jobs payload; a missing one 404s.
2. CAREERS-PAGE SCAN — fetch the careers URL (when known) and look for links/embeds that
   reveal the ATS host (boards.greenhouse.io/<slug>, jobs.lever.co/<slug>, ashbyhq.com/<slug>).

Detection is a build-time/registry tool — it never runs on a user's search path.
"""
from __future__ import annotations

import logging
import re

from .sources.http import fetch_json, fetch_text, post_json

log = logging.getLogger(__name__)


def _probe_greenhouse(slug: str) -> bool:
    j = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return isinstance(j, dict) and "jobs" in j


def _probe_lever(slug: str) -> bool:
    j = fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json", browser=True)
    return isinstance(j, list)


def _probe_ashby(slug: str) -> bool:
    j = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", browser=True)
    return isinstance(j, dict) and "jobs" in j


def _probe_workable(slug: str) -> bool:
    # v3 answers 200 + {"results": [...]} for EXISTING accounts (even with 0 published jobs —
    # future postings then appear automatically), 404 otherwise. POST-only endpoint.
    j = post_json(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", {"query": ""})
    return isinstance(j, dict) and "results" in j


# ats name -> "does this slug host a live board there?"
_PROBES: dict[str, callable] = {
    "greenhouse": _probe_greenhouse,
    "lever": _probe_lever,
    "ashby": _probe_ashby,
    "workable": _probe_workable,
}

_CAREERS_PATTERNS = [
    ("greenhouse", re.compile(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?[^\"']*for=([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?!api/)([\w-]+)", re.I)),
]


def slug_guesses(name: str) -> list[str]:
    """Likely board slugs for a company name: 'EGT Digital' -> egtdigital, egt-digital, egt."""
    base = re.sub(r"[^a-z0-9 ]+", "", name.lower()).strip()
    words = base.split()
    if not words:
        return []
    guesses = ["".join(words), "-".join(words)]
    if len(words) > 1:
        guesses.append(words[0])
    return list(dict.fromkeys(g for g in guesses if len(g) >= 3))


def probe_slug(ats: str, slug: str) -> bool:
    """True when `slug` is a live board on `ats` (public JSON answers with a jobs payload)."""
    return _PROBES[ats](slug)


def scan_careers_page(careers_url: str) -> tuple[str, str] | None:
    """Extract (ats, slug) from links/embeds on the company's careers page, if any."""
    html = fetch_text(careers_url)
    if not html:
        return None
    for ats, pat in _CAREERS_PATTERNS:
        m = pat.search(html)
        if m:
            return ats, m.group(1)
    return None


def detect(name: str, careers_url: str = "") -> tuple[str, str] | None:
    """Return (ats, slug) for `name`, or None when no supported ATS is found.
    The careers page (when given) wins — it's authoritative; slug probing is the fallback."""
    if careers_url:
        found = scan_careers_page(careers_url)
        if found:
            ats, slug = found
            if probe_slug(ats, slug):        # verify the page's link actually serves jobs
                return ats, slug
            log.info("careers page of %s names %s/%s but the board is dead", name, ats, slug)
    for slug in slug_guesses(name):
        for ats in _PROBES:
            if probe_slug(ats, slug):
                return ats, slug
    return None
