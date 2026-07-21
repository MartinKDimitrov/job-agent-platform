"""On-demand search: fetch from source adapters, score against a profile, persist matches.

This is the first end-to-end wiring of the product promise — "skills in → matches out" — for one
source type (Greenhouse). The daily scheduler (Step 16) will run the same `run_search` in the
background over a managed source list; here it is triggered synchronously by the user's
"Search now" button. Order matters for cost: cheap relevance pre-filter first, then a capped set
goes through requirement extraction + embeddings, so a 500-job board doesn't blow up the run.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Posting, Match
from .adapters import greenhouse
from .adapters.base import RawPosting, ingest
from .adapters.seed_boards import GREENHOUSE_BOARDS
from .extraction import extract_requirements
from .scoring import score

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


def run_search(db: Session, profile, boards=None, limit: int = DEFAULT_LIMIT) -> dict:
    """Fetch → pre-filter → ingest → extract → score for one profile. Returns a small summary."""
    boards = GREENHOUSE_BOARDS if boards is None else boards
    keywords = _profile_keywords(profile)

    # 1. fetch each board and keep only profile-relevant postings (cheap), then cap.
    fetched = 0
    candidates: list[RawPosting] = []
    for token, name in boards:
        posts = greenhouse.fetch(token, company_name=name)
        fetched += len(posts)
        candidates.extend(rp for rp in posts if _relevant(rp, keywords))
    candidates = candidates[:limit]

    # 2. persist (dedup by content_hash).
    ing = ingest(db, candidates)

    # 3. extract requirements (if missing) + score each candidate against the profile.
    ptext = profile.as_text()
    matched = 0
    for rp in candidates:
        post = db.execute(
            select(Posting).where(Posting.content_hash == rp.content_hash())).scalar_one_or_none()
        if not post:
            continue
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
        if sc >= profile.min_match:
            matched += 1
    db.commit()
    return {"fetched": fetched, "scored": len(candidates),
            "added": ing["added"], "matched": matched}
