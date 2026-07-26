"""karriere.nrw — the North Rhine-Westphalia public-sector job portal's OpenData REST API.

A legitimate, documented, unauthenticated JSON feed (open.nrw): one source, many public
authorities (~1000+ live NRW public-sector postings). A board-style source with no per-company
registry, like jobtech/remoteok — fetched blanket each daily run.

- LIST: GET https://api.karriere.nrw/v1.0/opennrw/suche?page=N -> {count, pages, items:[{uuid,
        title, authority, location, published, careerfield[], workingtime[], careergroup,
        benefit[], deadline, …}]}.
There is NO detail endpoint and the human job page is a JS SPA, so the posting text is composed
from the (rich) list metadata; the canonical/apply URL is the public page
https://karriere.nrw/stellenangebot/{uuid}. Codes are mapped to labels per the OpenData spec.
"""
from __future__ import annotations

import time
from datetime import datetime

from ...domain.entities import RawPosting
from .base import register
from .http import fetch_json

_SEARCH = "https://api.karriere.nrw/v1.0/opennrw/suche"
_JOB_URL = "https://karriere.nrw/stellenangebot/{}"
DEFAULT_MAX_PAGES = 150          # covers the whole feed (≈117 pages) with headroom
PAGE_DELAY = 0.3

_CAREERFIELD = {
    0: "Erziehung und Bildung", 1: "Gesundheit, Sport und Soziales",
    2: "Handwerk und Produktion", 3: "IT und Telekommunikation", 4: "Kunst und Kultur",
    5: "Landwirtschaft und Tierzucht", 6: "Presse- und Öffentlichkeitsarbeit", 7: "Recht",
    8: "Sicherheit und Ordnung", 9: "Sonstige Bereiche", 10: "Technische Verwaltung",
    11: "Umwelt und Verwaltung", 12: "Verkehr, Transport und Logistik", 13: "Verwaltung und Büro",
    14: "Wirtschaft, Finanzen und Marketing", 15: "Wissenschaft und Technik",
    16: "Zentrale Dienste und Personal"}
_WORKINGTIME = {0: "Teilzeit", 1: "Vollzeit", 2: "Vollzeit mit Teilzeitmöglichkeit"}
_CAREERGROUP = {0: "Einfacher Dienst", 1: "Mittlerer Dienst", 2: "Gehobener Dienst",
                3: "Höherer Dienst"}
_BENEFIT = {
    0: "Flexible Arbeitszeiten", 1: "Home-Office", 2: "Tiere geduldet",
    3: "Betriebliche Altersvorsorge", 4: "Kantine", 5: "Gute Verkehrsanbindung",
    6: "Parkplätze", 7: "Fort- und Weiterbildung", 8: "Gesundheitsmaßnahmen",
    9: "Kinderbetreuung", 10: "Mitarbeiterevents", 11: "Barrierefreiheit"}


def _labels(codes, mapping) -> str:
    return ", ".join(mapping[c] for c in (codes or []) if c in mapping)


def _authority(item: dict) -> str:
    return (item.get("authority") or item.get("contracting_authority") or "").strip()


def _describe(item: dict) -> str:
    """Compose a plain-text posting from the list metadata (no detail endpoint exists)."""
    lines = [item.get("title", "").strip()]
    for label, val in (
            ("Behörde", _authority(item)),
            ("Ort", (item.get("location") or "").strip()),
            ("Tätigkeitsfeld", _labels(item.get("careerfield"), _CAREERFIELD)),
            ("Laufbahngruppe", _CAREERGROUP.get(item.get("careergroup"), "")),
            ("Arbeitszeit", _labels(item.get("workingtime"), _WORKINGTIME)),
            ("Benefits", _labels(item.get("benefit"), _BENEFIT)),
            ("Bewerbungsfrist", (item.get("deadline") or "").strip())):
        if val:
            lines.append(f"{label}: {val}")
    return "\n".join(lines)


def _posted(item: dict) -> datetime | None:
    raw = (item.get("published") or "").strip()
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def fetch(max_pages: int = DEFAULT_MAX_PAGES, delay: float = PAGE_DELAY,
          sleep=time.sleep) -> list[RawPosting]:
    """All current NRW public-sector OpenData postings — paged list, metadata-composed text."""
    first = fetch_json(f"{_SEARCH}?page=1")
    if not isinstance(first, dict):
        return []
    pages = min(int(first.get("pages") or 1), max_pages)
    out: list[RawPosting] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        items = (first if page == 1 else (fetch_json(f"{_SEARCH}?page={page}") or {})).get("items") or []
        for it in items:
            uuid = (it.get("uuid") or "").strip()
            title = (it.get("title") or "").strip()
            if not uuid or not title or uuid in seen:
                continue
            desc = _describe(it)
            if len(desc) < 40:
                continue
            seen.add(uuid)
            url = _JOB_URL.format(uuid)
            out.append(RawPosting(
                source_kind="api", external_id=uuid, title=title, company=_authority(it),
                location=(it.get("location") or "").strip(), url=url, apply_url=url,
                description=desc, posted_at=_posted(it), raw={"source": "karriere_nrw"}))
        if page < pages:
            sleep(delay)
    return out


register("karriere_nrw", fetch)
