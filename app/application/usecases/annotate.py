"""Ingest-time requirement annotation (annotate-v1, approved 2026-07-23).

One LLM call per POSTING — not per user×posting — on the PLATFORM's key only (user BYOK
keys never produce shared data). Runs inside the background ingest with a per-cycle budget;
un-annotated postings keep working through token coverage + the per-user verification
fallback, so this is pure progressive enhancement. Failures skip the posting (retried next
cycle); version+fingerprint make re-annotation lazy and exact.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import settings
from ...data.llm import LLMError, get_provider
from ...data.models import Posting
from ...domain.prompts.annotate_v1 import (ANNOTATE_VERSION, build_annotate_prompt,
                                           parse_annotate_response, requirements_fingerprint,
                                           scored_requirements)
from ...domain.skills import canon_skill, is_known

log = logging.getLogger(__name__)


def _platform_llm():
    if not settings.server_llm_provider:
        return None
    p = get_provider(settings.server_llm_provider)
    if p is None:
        return None
    return p, settings.server_llm_api_key, (settings.annotate_model
                                            or settings.server_llm_model)


def annotate_posting(db: Session, post: Posting, llm,
                     unknown_seen: list[str] | None = None) -> bool:
    """Annotate one posting in place. True = annotated (stored), False = provider/parse
    failure (left untouched, retried next cycle). Skills the dictionary doesn't know are
    appended to `unknown_seen` — a sudden spike there means the market moved past skills-v1
    (Phase 6 observability: the count lands in CrawlRun stats)."""
    provider, api_key, model = llm
    scored = scored_requirements(post.requirements)
    fp = requirements_fingerprint(post.requirements)
    if not scored:
        post.annotation_version, post.annotation_fp = ANNOTATE_VERSION, fp
        return True                        # nothing to annotate — mark done for this fp
    system, prompt = build_annotate_prompt(post.title, scored)
    try:
        answer = provider.generate(system, prompt, api_key=api_key, model=model)
    except LLMError as e:
        log.warning("annotation failed for posting %s: %s", post.id, e)
        raise _RateLimited() if "rate limit" in str(e).lower() else _Failed()
    parsed = parse_annotate_response(answer, len(scored))
    if parsed is None:
        log.warning("unparseable annotation for posting %s", post.id)
        raise _Failed()
    # merge into a NEW requirements list (JSON column change detection needs reassignment);
    # skills are CANONIZED at write (and again at read — dictionary updates act instantly);
    # unknown-to-the-dictionary skills are logged: reviewing them is what grows the dictionary
    new_reqs = []
    scored_idx = 0
    fives = 0
    for r in post.requirements or []:
        r = dict(r)
        if r.get("kind", "must") in ("must", "nice"):
            if scored_idx in parsed:
                raw_skills, weight = parsed[scored_idx]
                unknown = [s for s in raw_skills if not is_known(s)]
                if unknown:
                    log.info("unknown skills (dictionary candidates): %s", unknown)
                    if unknown_seen is not None:
                        unknown_seen.extend(unknown)
                # ★5 cap: small models inflate importance, and an inflated ★5 arms the
                # must-gate — only the first FIVE_STAR_MAX keep it, the rest demote to ★4
                if weight >= 5:
                    fives += 1
                    if fives > settings.five_star_max:
                        weight = 4
                r["skills"] = sorted({canon_skill(s) for s in raw_skills})
                r["weight"] = weight
            scored_idx += 1
        new_reqs.append(r)
    post.requirements = new_reqs
    post.annotation_version, post.annotation_fp = ANNOTATE_VERSION, fp
    return True


class _Failed(Exception):
    """Annotation of one posting failed — skip it, retry next cycle."""


class _RateLimited(_Failed):
    """The provider rate-limited us — wait it out instead of burning the budget."""


def annotate_postings(db: Session, budget: int | None = None, delay: float = 8.0,
                      rate_limit_wait: float = 30.0, sleep=time.sleep) -> dict:
    """Annotate up to `budget` live postings whose annotation is missing or stale
    (version/fingerprint mismatch). Platform LLM lane only; silently a no-op without one."""
    budget = settings.annotate_budget if budget is None else budget
    llm = _platform_llm()
    if not budget or llm is None:
        return {"annotated": 0, "failed": 0, "unknown_skills": 0}
    annotated = failed = rate_limited = 0
    unknown_seen: list[str] = []
    rows = db.execute(select(Posting).where(Posting.is_live.is_(True))
                      .order_by(Posting.first_seen.desc())).scalars()
    for post in rows:
        if annotated + failed >= budget:
            break
        if (post.annotation_version == ANNOTATE_VERSION
                and post.annotation_fp == requirements_fingerprint(post.requirements)):
            continue
        if not scored_requirements(post.requirements):
            # cheap bookkeeping, no LLM call — doesn't consume the budget
            post.annotation_version = ANNOTATE_VERSION
            post.annotation_fp = requirements_fingerprint(post.requirements)
            continue
        if annotated + failed:
            sleep(delay)
        try:
            annotate_posting(db, post, llm, unknown_seen)
            annotated += 1
            db.commit()      # per-posting: a multi-hour run must not hold row locks
        except _RateLimited:
            rate_limited += 1
            failed += 1
            if rate_limited > 3:         # persistent limiting — yield, the next cycle continues
                break
            sleep(rate_limit_wait)       # one-off burst: wait out the window and keep going
        except _Failed:
            # the fast model sometimes mangles JSON — one retry on the bigger default model
            big = (llm[0], llm[1], settings.server_llm_model)
            if big[2] and big[2] != llm[2]:
                try:
                    annotate_posting(db, post, big, unknown_seen)
                    annotated += 1
                    continue
                except _Failed:
                    pass
            failed += 1
    db.commit()
    return {"annotated": annotated, "failed": failed, "unknown_skills": len(unknown_seen)}
