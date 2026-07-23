"""France Travail adapter (ex Pôle Emploi) — France's public employment service.

The Offres d'emploi v2 API is free but needs OAuth2 CLIENT CREDENTIALS from francetravail.io
(register an app, tick the "API Offres d'emploi" product). Without credentials in .env
(FRANCETRAVAIL_CLIENT_ID/SECRET) the adapter is a silent no-op — the ingest degrades, never
breaks. Third adapter of the EU boards plan (JobTech → Arbeitsagentur → **France Travail** →
EURES).

Flow: one token per ~25 min (cached in-process), then one search per profile role term.
`origineOffre.urlOrigine` (the employer's own posting when the offer came from partner
sites) wins as apply link; otherwise the candidate-facing France Travail page.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx

from ...core.config import settings
from ...domain.entities import RawPosting
from .base import register

log = logging.getLogger(__name__)

TOKEN_URL = ("https://entreprise.francetravail.fr/connexion/oauth2/access_token"
             "?realm=%2Fpartenaire")
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
JOB_PAGE = "https://candidat.francetravail.fr/offres/recherche/detail/{oid}"
SCOPE = "api_offresdemploiv2 o2dsoffre"
DEFAULT_RANGE = "0-29"          # per term; the API pages via a Range-style param

_token: dict = {"value": "", "expires": 0.0}


def _get_token() -> str:
    """Client-credentials token, cached until shortly before expiry."""
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    try:
        r = httpx.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": settings.francetravail_client_id,
            "client_secret": settings.francetravail_client_secret,
            "scope": SCOPE,
        }, timeout=15)
        r.raise_for_status()
        j = r.json()
        _token["value"] = j.get("access_token", "")
        _token["expires"] = time.time() + float(j.get("expires_in", 1499))
    except (httpx.HTTPError, ValueError) as e:
        log.warning("francetravail token failed: %s", e)
        _token["value"] = ""
    return _token["value"]


def _search(term: str, token: str) -> list[dict]:
    try:
        r = httpx.get(SEARCH_URL, params={"motsCles": term, "range": DEFAULT_RANGE},
                      headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code == 204:            # no results
            return []
        r.raise_for_status()
        return (r.json() or {}).get("resultats") or []
    except (httpx.HTTPError, ValueError) as e:
        log.warning("francetravail search '%s' failed: %s", term, e)
        return []


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def fetch(search_terms: list[str] | None = None) -> list[RawPosting]:
    if not (settings.francetravail_client_id and settings.francetravail_client_secret):
        return []                            # not configured — silent no-op
    token = _get_token()
    if not token:
        return []
    out: dict[str, RawPosting] = {}
    for term in search_terms or []:
        for offre in _search(term, token):
            oid = str(offre.get("id") or "")
            if not oid or oid in out:
                continue
            page = JOB_PAGE.format(oid=oid)
            origin = ((offre.get("origineOffre") or {}).get("urlOrigine") or "").strip()
            lieu = (offre.get("lieuTravail") or {}).get("libelle") or ""
            out[oid] = RawPosting(
                source_kind="board_api",
                external_id=oid,
                title=offre.get("intitule") or "",
                company=(offre.get("entreprise") or {}).get("nom") or "",
                location=f"{lieu}, France" if lieu else "France",
                url=page,
                apply_url=origin or page,
                description=offre.get("description") or "",
                posted_at=_parse_dt(offre.get("dateCreation")),
                raw={"source": "francetravail", "term": term},
            )
    return list(out.values())


register("francetravail", fetch)
