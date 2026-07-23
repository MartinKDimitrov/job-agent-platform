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

log = logging.getLogger(__name__)


def _platform_llm():
    if not settings.server_llm_provider:
        return None
    p = get_provider(settings.server_llm_provider)
    if p is None:
        return None
    return p, settings.server_llm_api_key, settings.server_llm_model


def annotate_posting(db: Session, post: Posting, llm) -> bool:
    """Annotate one posting in place. True = annotated (stored), False = provider/parse
    failure (left untouched, retried next cycle)."""
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
        return False
    parsed = parse_annotate_response(answer, len(scored))
    if parsed is None:
        log.warning("unparseable annotation for posting %s", post.id)
        return False
    # merge into a NEW requirements list (JSON column change detection needs reassignment)
    new_reqs = []
    scored_idx = 0
    for r in post.requirements or []:
        r = dict(r)
        if r.get("kind", "must") in ("must", "nice"):
            if scored_idx in parsed:
                r["skills"], r["weight"] = parsed[scored_idx]
            scored_idx += 1
        new_reqs.append(r)
    post.requirements = new_reqs
    post.annotation_version, post.annotation_fp = ANNOTATE_VERSION, fp
    return True


def annotate_postings(db: Session, budget: int | None = None, delay: float = 0.3,
                      sleep=time.sleep) -> dict:
    """Annotate up to `budget` live postings whose annotation is missing or stale
    (version/fingerprint mismatch). Platform LLM lane only; silently a no-op without one."""
    budget = settings.annotate_budget if budget is None else budget
    llm = _platform_llm()
    if not budget or llm is None:
        return {"annotated": 0, "failed": 0}
    annotated = failed = 0
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
        if annotate_posting(db, post, llm):
            annotated += 1
        else:
            failed += 1
    db.commit()
    return {"annotated": annotated, "failed": failed}
