"""LLM coverage verification (approved 2026-07-22): after keyword scoring, a cheap LLM
re-labels the covered/missing split for the TOP matches — the ones the user actually sees.

Cost/latency discipline:
- runs only for matches above the profile's threshold, newest-first, capped at
  settings.verify_top_n per search; a verified match is never re-verified (llm_verified),
  so re-searches add zero LLM calls;
- provider chain = the user's BYOK key, else the platform's free lane (no doc-quota use);
  with neither, verification silently does nothing;
- STRICT-JSON answers; any parse/provider failure leaves the match untouched (best-effort
  by design — scoring must never depend on an LLM being up).
Scores are recomputed with domain.scoring.blend/coverage_ratio — the same formula as the
base score, so the two paths cannot drift.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import settings
from ...data.keystore import get_config
from ...data.llm import LLMError, get_provider
from ...data.models import Match, Posting, Profile
from ...domain.prompts.verify_v1 import build_verify_prompt, parse_verify_response
from ...domain.scoring import blend, coverage_ratio, semantic_pct

log = logging.getLogger(__name__)

_SCORED_KINDS = ("must", "nice")


def _llm_for(db: Session, user_id: int):
    """(provider, api_key, model) — BYOK first, else the platform lane; None when neither."""
    cfg = get_config(db, user_id)
    if cfg is not None:
        p = get_provider(cfg["provider"])
        if p is not None:
            return p, cfg["api_key"], cfg["model"]
    if settings.server_llm_provider:
        p = get_provider(settings.server_llm_provider)
        if p is not None:
            return p, settings.server_llm_api_key, settings.server_llm_model
    return None


def verify_match(db: Session, profile, match: Match, post: Posting, llm) -> bool:
    """Verify one match in place. Returns True when the match was checked (even if nothing
    moved). False = provider/parse failure, match untouched."""
    provider, api_key, model = llm
    scored = [r for r in (match.covered or []) + (match.missing or [])
              if isinstance(r, dict) and r.get("kind", "must") in _SCORED_KINDS]
    if not scored:
        match.llm_verified = True          # nothing to verify
        return True
    system, prompt = build_verify_prompt(profile, scored)
    try:
        answer = provider.generate(system, prompt, api_key=api_key, model=model)
    except LLMError as e:
        log.warning("coverage verification failed for match %s: %s", match.id, e)
        return False
    hit_idx = parse_verify_response(answer, len(scored))
    if hit_idx is None:
        log.warning("unparseable verification answer for match %s", match.id)
        return False

    hits = {id(r): (i in hit_idx) for i, r in enumerate(scored)}
    covered, missing = [], []
    for r in (match.covered or []) + (match.missing or []):
        if isinstance(r, dict) and id(r) in hits:
            (covered if hits[id(r)] else missing).append(r)
        else:                               # resp/soft entries keep their original bucket
            src_covered = r in (match.covered or [])
            (covered if src_covered else missing).append(r)
    from .search import posting_freshness
    from ...domain.salary import parse_salary, posting_salary, salary_factor
    from ...domain.scoring import must_gate_cap
    pairs = [(r, hits[id(r)]) for r in scored]
    kw = coverage_ratio(pairs)
    sem = semantic_pct(profile.embedding, post.embedding)
    base = blend(sem, kw, settings.semantic_weight)
    if settings.must_gate_cap:
        gate = must_gate_cap(pairs, settings.must_gate_cap)
        if gate is not None:
            base = min(base, gate)
    # same soft multipliers as the base scorer (freshness × salary) — the paths must not drift
    soft = posting_freshness(post) * salary_factor(
        posting_salary(post), parse_salary(profile.salary_expectation or ""),
        low=settings.salary_low_factor, fit=settings.salary_fit_boost)
    match.score = min(100, round(base * soft * 100))
    match.covered, match.missing = covered, missing
    match.llm_verified = True
    return True


def verify_top_matches_async(session_factory, profile_id: int) -> None:
    """Fire-and-forget the LLM verification OFF the request path (daemon thread, own session).
    A user search with many fresh matches returns immediately; the verified covered/missing
    split lands a few seconds later (visible on the next page load). Best-effort — a provider
    outage or rate limit just leaves the matches keyword-scored until the next search."""
    def _run():
        try:
            with session_factory() as db:
                p = db.get(Profile, profile_id)
                if p is not None:
                    verify_top_matches(db, p)
        except Exception:  # noqa: BLE001 — verification is best-effort, never crash the worker
            log.warning("async coverage verification failed for profile %s", profile_id,
                        exc_info=True)

    threading.Thread(target=_run, name=f"verify-{profile_id}", daemon=True).start()


def verify_top_matches(db: Session, profile, top_n: int | None = None) -> dict:
    """Verify the unverified top-of-feed matches for `profile`, within budget."""
    top_n = settings.verify_top_n if top_n is None else top_n
    if not top_n:
        return {"verified": 0, "failed": 0}
    llm = _llm_for(db, profile.user_id)
    if llm is None:
        return {"verified": 0, "failed": 0}
    rows = db.execute(
        select(Match, Posting).join(Posting, Match.posting_id == Posting.id)
        .where(Match.profile_id == profile.id, Match.llm_verified.is_(False),
               Match.score >= profile.min_match, Posting.is_live.is_(True))
        .order_by(Match.score.desc()).limit(top_n)).all()
    from ...domain.prompts.annotate_v1 import ANNOTATE_VERSION
    verified = failed = 0
    for match, post in rows:
        if post.annotation_version == ANNOTATE_VERSION:
            # deterministic coverage already came from the shared annotation — no LLM needed
            match.llm_verified = True
            verified += 1
            continue
        if verify_match(db, profile, match, post, llm):
            verified += 1
        else:
            failed += 1
            break   # a failing provider (rate limit/outage) would fail 8x — stop burning
                    # the search latency; the next search retries the rest
    db.commit()
    return {"verified": verified, "failed": failed}
