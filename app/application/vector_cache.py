"""Hybrid recall (Phase 5): vector door + skill door.

VECTOR door — on Postgres the cosine search runs SERVER-SIDE via pgvector's HNSW index
(`embedding <=> q`), so a search never pulls the ~387k×384 vector matrix over the tunnel
(that measured ~90s + ~600MB RAM). On SQLite (tests) there is no pgvector, so we fall back
to the in-process numpy matrix.

SKILL door — canonical-skill overlap can't be expressed in SQL (canon_skill is Python), so
the per-posting skill sets stay cached in RAM, rebuilt lazily after each ingest invalidates
it (and warmed off the request path — see `warm`). On Postgres that cache no longer carries
the vectors, only the (much lighter) requirement skills.
"""
from __future__ import annotations

import threading

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..core.config import settings
from ..data.models import Posting
from ..domain.skills import canon_skill

_lock = threading.Lock()
_state: dict = {"ids": None, "matrix": None, "skills": None, "stale": True}


def _is_sqlite(db: Session) -> bool:
    return db.bind.dialect.name == "sqlite"


def invalidate() -> None:
    """Call after any ingest/hygiene pass — the next search reloads."""
    _state["stale"] = True


def _load(db: Session) -> None:
    # The skill door always needs requirements. The vector matrix is only built for SQLite —
    # Postgres does vector recall in SQL and never touches this matrix.
    keep_vectors = _is_sqlite(db)
    cols = ((Posting.id, Posting.embedding, Posting.requirements) if keep_vectors
            else (Posting.id, Posting.requirements))
    ids, vecs, skills = [], [], {}
    for row in db.execute(select(*cols)
                          .where(Posting.is_live.is_(True), Posting.embedding.isnot(None))):
        if keep_vectors:
            pid, emb, reqs = row
            ids.append(pid)
            vecs.append(np.asarray(emb, dtype=np.float32))
        else:
            pid, reqs = row
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


def warm(db: Session) -> None:
    """Eagerly build the skill cache OFF the request path (at startup, and after each ingest
    invalidates it) so the first user search doesn't pay the reload over the tunnel. No-op
    when already warm."""
    _ensure(db)


def similar_posting_ids(db: Session, profile_vec, min_cosine: float, limit: int | None = None) -> set[int]:
    """Live posting ids whose stored vector is within `min_cosine` of the profile's.

    Postgres: an HNSW ANN query — `ORDER BY embedding <=> q LIMIT cap`, kept to those within
    the cosine threshold. `hnsw.ef_search` is raised to the cap so recall isn't throttled to
    the default ~40 candidates (SET LOCAL → transaction-scoped, no pooled-connection leak).
    The result is approximate (~98% of the exact set at the 0.87 boundary) but this is a
    candidate-generation door that gets scored and trimmed to `recall_max_candidates` anyway."""
    if profile_vec is None:
        return set()
    if _is_sqlite(db):
        _ensure(db)
        if not len(_state["ids"]):
            return set()
        sims = _state["matrix"] @ np.asarray(profile_vec, dtype=np.float32)
        return set(int(x) for x in _state["ids"][sims >= min_cosine])
    cap = limit or settings.recall_max_candidates
    max_dist = 1.0 - min_cosine
    dist = Posting.embedding.cosine_distance(profile_vec)
    db.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": max(cap, 100)})
    rows = db.execute(select(Posting.id, dist.label("d"))
                      .where(Posting.is_live.is_(True), Posting.embedding.isnot(None))
                      .order_by(dist).limit(cap)).all()
    return {pid for pid, d in rows if d is not None and d <= max_dist}


def postings_sharing_skills(db: Session, profile_skills: set[str]) -> set[int]:
    """Live posting ids sharing at least one (non-generic) canonical skill with the profile."""
    if not profile_skills:
        return set()
    _ensure(db)
    return {pid for pid, sk in _state["skills"].items() if sk & profile_skills}
