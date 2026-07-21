"""On-demand search: fetch from source adapters, score against a profile, persist matches.

This is the first end-to-end wiring of the product promise — "skills in → matches out" — for one
source type (Greenhouse). The daily scheduler (Step 16) will run the same `run_search` in the
background over a managed source list; here it is triggered synchronously by the user's
"Search now" button. Order matters for cost: cheap relevance pre-filter first, then a capped set
goes through requirement extraction + embeddings, so a 500-job board doesn't blow up the run.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Posting, Match
from .adapters import greenhouse, dev_bg, remoteok, wwr, lever, ashby
from .adapters.base import RawPosting, ingest
from .adapters.seed_boards import GREENHOUSE_BOARDS, LEVER_COMPANIES, ASHBY_COMPANIES
from .extraction import extract_requirements
from .scoring import score
from .filters import passes_hard_filters

log = logging.getLogger(__name__)


def _lever_all() -> list[RawPosting]:
    return [rp for slug, name in LEVER_COMPANIES for rp in lever.fetch(slug, name)]


def _ashby_all() -> list[RawPosting]:
    return [rp for slug, name in ASHBY_COMPANIES for rp in ashby.fetch(slug, name)]


# Fast sources run on every "Search now" (kept snappy): dev.bg RSS (BG market).
FAST_SOURCES = [dev_bg.fetch]
# Heavier aggregators/ATS run in the daily background job only.
EXTRA_SOURCES = [remoteok.fetch, wwr.fetch, _lever_all, _ashby_all]


def _safe(fn) -> list[RawPosting]:
    """Run a source, isolating its failure — one broken source must not kill the whole run."""
    try:
        return list(fn())
    except Exception as e:  # noqa: BLE001 — any adapter error degrades to "no postings"
        log.warning("source %s failed: %s", getattr(fn, "__name__", fn), e)
        return []

DEFAULT_LIMIT = 40
_TOKEN_RE = re.compile(r"[a-z0-9\+\#\.]+")


def _profile_keywords(profile) -> set[str]:
    text = f"{profile.target_roles or ''} {profile.skills or ''}".lower()
    return {tok for tok in _TOKEN_RE.findall(text) if len(tok) > 2}


def _relevant(rp: RawPosting, keywords: set[str]) -> bool:
    """Cheap pre-filter: keep a posting only if its title mentions a profile keyword. Avoids
    embedding hundreds of obviously-irrelevant roles (e.g. Sales jobs for an Android profile)."""
    if not keywords:
        return True
    return any(k in (rp.title or "").lower() for k in keywords)


def fetch_all(boards=None) -> list[RawPosting]:
    """Fetch the fast sources once (Greenhouse boards + dev.bg RSS) — used by both "Search now"
    and the daily job. Each source is error-isolated. Heavier aggregators (RemoteOK/WWR/Lever/
    Ashby via fetch_extra) and crawl-delayed sources (JobTiger) are added by the daily job only."""
    boards = GREENHOUSE_BOARDS if boards is None else boards
    out: list[RawPosting] = []
    for token, name in boards:
        try:
            out.extend(greenhouse.fetch(token, company_name=name))
        except Exception as e:  # noqa: BLE001
            log.warning("greenhouse %s failed: %s", token, e)
    for src in FAST_SOURCES:
        out.extend(_safe(src))
    return out


def fetch_extra() -> list[RawPosting]:
    """RemoteOK / WWR / Lever / Ashby — broader coverage for the daily background run."""
    out: list[RawPosting] = []
    for src in EXTRA_SOURCES:
        out.extend(_safe(src))
    return out


def run_search(db: Session, profile, boards=None, limit: int = DEFAULT_LIMIT,
               raw_postings=None) -> dict:
    """Fetch → pre-filter → ingest → extract → score for one profile. Returns a small summary.
    Pass `raw_postings` to score an already-fetched batch (used by the daily digest job)."""
    boards = GREENHOUSE_BOARDS if boards is None else boards
    keywords = _profile_keywords(profile)

    # 1. get postings (fetch, or reuse a pre-fetched batch) and keep only relevant ones, capped.
    if raw_postings is None:
        raw_postings = fetch_all(boards)
    fetched = len(raw_postings)
    candidates = [rp for rp in raw_postings if _relevant(rp, keywords)][:limit]

    # 2. persist (dedup by content_hash).
    ing = ingest(db, candidates)

    # 3. hard filters (location/seniority) BEFORE scoring, then extract + score what survives.
    ptext = profile.as_text()
    scored = filtered = matched = 0
    for rp in candidates:
        post = db.execute(
            select(Posting).where(Posting.content_hash == rp.content_hash())).scalar_one_or_none()
        if not post:
            continue
        ok, _reason = passes_hard_filters(profile, post.title, post.location, post.description)
        if not ok:
            filtered += 1
            continue                       # dropped before any embedding cost
        if not post.requirements:
            post.requirements = extract_requirements(post.description or "")
        sc, covered, missing = score(ptext, post.description or post.title, post.requirements)
        existing = db.execute(select(Match).where(
            Match.profile_id == profile.id, Match.posting_id == post.id)).scalar_one_or_none()
        if existing:
            existing.score, existing.covered, existing.missing = sc, covered, missing
        else:
            db.add(Match(profile_id=profile.id, posting_id=post.id,
                         score=sc, covered=covered, missing=missing))
        scored += 1
        if sc >= profile.min_match:
            matched += 1
    db.commit()
    return {"fetched": fetched, "candidates": len(candidates), "filtered": filtered,
            "scored": scored, "added": ing["added"], "matched": matched}
