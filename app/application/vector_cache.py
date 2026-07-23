"""In-process vector/skill cache for hybrid recall (Phase 5).

The recall path needs cosine against EVERY live posting on every search — parsing all
stored vectors per request would dominate the latency. This cache keeps one normalized
numpy matrix (+ per-posting canonical skill sets) in RAM, refreshed lazily after each
ingest cycle invalidates it. Zero infrastructure; sub-millisecond up to tens of thousands
of rows. At deploy scale the same query can move into pgvector SQL (extension already
installed on staging) — the call sites won't change.
"""
from __future__ import annotations

import threading

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data.models import Posting
from ..domain.skills import canon_skill

_lock = threading.Lock()
_state: dict = {"ids": None, "matrix": None, "skills": None, "stale": True}


def invalidate() -> None:
    """Call after any ingest/hygiene pass — the next search reloads."""
    _state["stale"] = True


def _load(db: Session) -> None:
    ids, vecs, skills = [], [], {}
    for pid, emb, reqs in db.execute(
            select(Posting.id, Posting.embedding, Posting.requirements)
            .where(Posting.is_live.is_(True), Posting.embedding.isnot(None))):
        ids.append(pid)
        vecs.append(np.asarray(emb, dtype=np.float32))
        skills[pid] = {canon_skill(s)
                       for r in (reqs or []) if isinstance(r, dict)
                       for s in (r.get("skills") or [])}
    _state["ids"] = np.asarray(ids)
    _state["matrix"] = np.vstack(vecs) if vecs else np.zeros((0, 1), dtype=np.float32)
    _state["skills"] = skills
    _state["stale"] = False


def _ensure(db: Session) -> None:
    if _state["stale"] or _state["ids"] is None:
        with _lock:
            if _state["stale"] or _state["ids"] is None:
                _load(db)


def similar_posting_ids(db: Session, profile_vec, min_cosine: float) -> set[int]:
    """Live posting ids whose stored vector is within `min_cosine` of the profile's."""
    if profile_vec is None:
        return set()
    _ensure(db)
    if not len(_state["ids"]):
        return set()
    sims = _state["matrix"] @ np.asarray(profile_vec, dtype=np.float32)
    return set(int(x) for x in _state["ids"][sims >= min_cosine])


def postings_sharing_skills(db: Session, profile_skills: set[str]) -> set[int]:
    """Live posting ids sharing at least one (non-generic) canonical skill with the profile."""
    if not profile_skills:
        return set()
    _ensure(db)
    return {pid for pid, sk in _state["skills"].items() if sk & profile_skills}
