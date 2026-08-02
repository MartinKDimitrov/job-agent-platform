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
from sqlalchemy import or_, select, text
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


# Location strings arrive as "BG", "София, BG", "Bulgaria", "Sofia, Bulgaria" — so a country is
# matched by its name AND its ISO code. Only the markets we actually ingest need an entry; an
# unknown country simply skips the narrowing.
_COUNTRY_SQL: dict[str, tuple[str, ...]] = {
    "bulgaria": ("%bulgaria%", "%българия%", "%bg%"), "germany": ("%germany%", "%deutschland%", "%de%"),
    "france": ("%france%", "%fr%"), "spain": ("%spain%", "%españa%", "%es%"),
    "italy": ("%italy%", "%italia%", "%it%"), "netherlands": ("%netherlands%", "%nl%"),
    "poland": ("%poland%", "%polska%", "%pl%"), "romania": ("%romania%", "%ro%"),
    "greece": ("%greece%", "%gr%"), "ireland": ("%ireland%", "%ie%"),
    "austria": ("%austria%", "%at%"), "belgium": ("%belgium%", "%be%"),
    "switzerland": ("%switzerland%", "%ch%"), "denmark": ("%denmark%", "%dk%"),
    "united kingdom": ("%united kingdom%", "%uk%", "%gb%"),
}


def geo_narrowing(profile):
    """A SQL predicate restricting the vector search to postings the candidate could take.

    Screening AFTER the ANN is not enough: the nearest postings to a trade profile are all in
    other countries (a Bulgarian welder's top matches are Irish), so the index budget — bounded
    by pgvector's ef_search ceiling of 1000 — is spent entirely on rows the location filter will
    discard, and the one job in his own city never surfaces. Narrowing FIRST makes the ANN return
    the nearest ELIGIBLE postings instead. Someone willing to relocate gets no narrowing."""
    if getattr(profile, "relocate", False):
        return None
    pats = _COUNTRY_SQL.get((getattr(profile, "country", "") or "").strip().lower())
    if not pats:
        return None
    conds = [Posting.location.ilike(p) for p in pats]
    conds += [Posting.location.is_(None), Posting.location == "",
              Posting.location.ilike("%remote%"), Posting.location.ilike("%anywhere%")]
    return or_(*conds)


def ranked_candidates(db: Session, profile_vec, limit: int,
                      min_cosine: float | None = None, extra_filter=None) -> list[tuple]:
    """Like `ranked_posting_ids`, but yields (id, title, location) so the caller can drop the
    geographically impossible BEFORE spending candidate budget on them. Without this the whole
    budget goes to the semantically nearest postings, which for a trade are all abroad: a Sofia
    welder's top 400 were Irish and Danish, every one of them dropped by the location filter a
    moment later, while the Bulgarian "Заварчик" postings — the only ones he could take — sat
    further down the ranking and never entered."""
    if profile_vec is None:
        return []
    floor = settings.recall_rank_floor if min_cosine is None else min_cosine
    if _is_sqlite(db):
        ids = ranked_posting_ids(db, profile_vec, limit, min_cosine)
        rows = db.execute(select(Posting.id, Posting.title, Posting.location)
                          .where(Posting.id.in_(ids))).all() if ids else []
        order = {pid: i for i, pid in enumerate(ids)}
        return sorted(rows, key=lambda r: order.get(r[0], 1 << 30))
    dist = Posting.embedding.cosine_distance(profile_vec)
    # pgvector caps hnsw.ef_search at 1000; asking for more makes the SET fail and the index
    # silently falls back to its default ~40, which is why an oversampled request came back with
    # 51 rows instead of thousands. It also bounds how deep the rank door can ever look.
    db.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": min(1000, max(limit, 100))})
    q = (select(Posting.id, Posting.title, Posting.location, dist.label("d"))
         .where(Posting.is_live.is_(True), Posting.embedding.isnot(None)))
    if extra_filter is not None:
        q = q.where(extra_filter)
    rows = db.execute(q.order_by(dist).limit(limit)).all()
    return [(pid, title, loc) for pid, title, loc, d in rows
            if d is not None and (1.0 - d) >= floor]


def ranked_posting_ids(db: Session, profile_vec, limit: int,
                       min_cosine: float | None = None) -> list[int]:
    """The `limit` NEAREST live postings, in order, with NO cosine threshold.

    `similar_posting_ids` answers "which postings are confidently similar" against an ABSOLUTE
    bar (`recall_min_cosine`) that was calibrated on IT profiles, whose long descriptions sit
    high in cosine space. Short trade titles never reach it — a welder profile scores 0.763
    against "Заварчик" and 0.833 against "Site Welder" at a 0.87 bar — so entire professions
    recalled nothing at all and their feeds filled with whatever else the other doors found.

    Rank has no such bias: everybody gets their own best candidates, in any language, and the
    scoring + hard filters downstream decide what actually survives. `min_cosine` is a LOW floor
    (not the confident bar) so that plainly unrelated postings still never enter."""
    if profile_vec is None:
        return []
    floor = settings.recall_rank_floor if min_cosine is None else min_cosine
    if _is_sqlite(db):
        _ensure(db)
        if not len(_state["ids"]):
            return []
        sims = _state["matrix"] @ np.asarray(profile_vec, dtype=np.float32)
        order = [i for i in np.argsort(-sims)[:limit] if sims[i] >= floor]
        return [int(x) for x in _state["ids"][order]]
    dist = Posting.embedding.cosine_distance(profile_vec)
    db.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": min(1000, max(limit, 100))})
    rows = db.execute(select(Posting.id, dist.label("d"))
                      .where(Posting.is_live.is_(True), Posting.embedding.isnot(None))
                      .order_by(dist).limit(limit)).all()
    return [pid for pid, d in rows if d is not None and (1.0 - d) >= floor]


def postings_sharing_skills(db: Session, profile_skills: set[str]) -> set[int]:
    """Live posting ids sharing at least one (non-generic) canonical skill with the profile."""
    if not profile_skills:
        return set()
    _ensure(db)
    return {pid for pid, sk in _state["skills"].items() if sk & profile_skills}
