"""Arbeitsagentur adapter — Germany's federal employment agency (Bundesagentur für Arbeit).

The Jobsuche API is public: the well-known client key `jobboerse-jobsuche` (the same one the
official web app sends) unlocks read-only search — no registration. Second adapter of the EU
boards plan (JobTech → **Arbeitsagentur** → France Travail → EURES).

Two calls per posting reach the full text:
- SEARCH `pc/v4/jobs?was=<term>` — refnr, title, employer, city, dates (no description);
- DETAILS `pc/v4/jobdetails/<urlsafe-b64(refnr)>` — `stellenangebotsBeschreibung` (markdown-ish
  plain text). Detail GETs are paced like the Workable adapter; verified live 2026-07-24
  (the v2 details endpoint of older writeups is gone — 403).

Targeted like dev.bg/JobTech: one search per unique profile role term per cycle. `externeUrl`
(the employer's own posting, present on a subset) wins as apply link; otherwise the Jobsuche
detail page. German-language postings are fine — E5 is multilingual and the skills dictionary
carries the tech vocabulary.
"""
from __future__ import annotations

import base64
import time
from datetime import datetime

from ...domain.entities import RawPosting
from .base import register
from .http import fetch_json

SEARCH_API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
DETAILS_API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{b64}"
JOB_PAGE = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}     # public client key, not a secret

DEFAULT_SIZE = 30          # per term — bounds the paced detail GETs
DETAIL_DELAY = 0.2


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:19])
    except (ValueError, TypeError):
        return None


def _b64(refnr: str) -> str:
    return base64.urlsafe_b64encode(refnr.encode("utf-8")).decode("ascii")


def _location(hit: dict) -> str:
    ort = hit.get("arbeitsort") or {}
    parts = [ort.get("ort"), ort.get("region"), "Germany"]
    return ", ".join(p for p in parts if p)


def fetch(search_terms: list[str] | None = None, size: int = DEFAULT_SIZE,
          delay: float = DETAIL_DELAY, sleep=time.sleep) -> list[RawPosting]:
    """One search per term + one paced details GET per new posting."""
    out: dict[str, RawPosting] = {}
    for term in search_terms or []:
        data = fetch_json(SEARCH_API, params={"was": term, "size": size}, headers=_HEADERS)
        if not isinstance(data, dict):
            continue
        for hit in data.get("stellenangebote") or []:
            refnr = hit.get("refnr") or ""
            if not refnr or refnr in out:
                continue
            det = fetch_json(DETAILS_API.format(b64=_b64(refnr)), headers=_HEADERS)
            desc = (det or {}).get("stellenangebotsBeschreibung") or ""
            if not desc:
                continue           # no text -> no requirements -> the posting can't score
            url = JOB_PAGE.format(refnr=refnr)
            out[refnr] = RawPosting(
                source_kind="board_api",
                external_id=refnr,
                title=hit.get("titel") or hit.get("beruf") or "",
                company=hit.get("arbeitgeber") or "",
                location=_location(hit),
                url=url,
                apply_url=hit.get("externeUrl") or url,
                description=desc,
                posted_at=_parse_dt(hit.get("aktuelleVeroeffentlichungsdatum")),
                raw={"source": "arbeitsagentur", "term": term},
            )
            sleep(delay)
    return list(out.values())


register("arbeitsagentur", fetch)
