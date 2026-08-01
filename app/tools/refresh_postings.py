"""Recompute the DERIVED fields of stored postings, keeping them consistent with each other.

    python -m app.tools.refresh_postings                 # live postings with a long description
    python -m app.tools.refresh_postings --min-len 0     # every live posting
    python -m app.tools.refresh_postings --limit 500     # a slice, for a quick check
    python -m app.tools.refresh_postings --verify-vectors  # audit/repair every stored vector

A posting carries three fields derived from its raw text: the extracted `requirements`, the
`education_level`, and the `embedding`. Ingest computes them once; whenever the extractor changes
(new boilerplate rules, a new language) the STORED values are stale and every search keeps scoring
against yesterday's rules.

The trap this tool exists to close: the embedding is built FROM the requirements
(`posting_embed_text` = title + must/nice/resp), so re-extracting requirements alone silently
leaves the vector encoding the OLD text — measured drift up to 0.87 cosine on cleaned postings,
which is ~37 points of semantic score. Enrichment won't catch it either: it only re-embeds on a
NULL vector or an `EMBED_VERSION` bump. So this pass recomputes the embedding whenever the embed
INPUT changed, and writes only rows that actually differ (the tunnel sees minimal traffic).
"""
from __future__ import annotations

import sys
import time

from sqlalchemy import func, select

from ..data.db import SessionLocal
from ..data.models import Posting
from ..domain.extraction import extract_requirements
from ..domain.filters import extract_qualification_level
from ..domain.scoring import EMBED_VERSION, embed_passage, posting_embed_text

CHUNK = 400
_SAME = 0.9999   # cosine above which the recomputed vector is treated as unchanged


def _cos(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    return float(a @ b)


def _as_list(v):
    return None if v is None else (v.tolist() if hasattr(v, "tolist") else list(v))


def run(min_len: int = 800, limit: int | None = None, verify_vectors: bool = False,
        log=print) -> dict:
    q = select(Posting.id).where(Posting.is_live.is_(True))
    if min_len:
        q = q.where(func.length(Posting.description) > min_len)
    q = q.order_by(Posting.id)
    if limit:
        q = q.limit(limit)
    with SessionLocal() as db:
        ids = [r[0] for r in db.execute(q).all()]
    total = len(ids)
    log(f"targets: {total}")
    seen = reqs_changed = edu_set = vec_changed = 0
    for i in range(0, total, CHUNK):
        batch = ids[i:i + CHUNK]
        for attempt in range(3):
            try:
                with SessionLocal() as db:
                    for p in db.execute(
                            select(Posting).where(Posting.id.in_(batch))).scalars():
                        seen += 1
                        old_input = posting_embed_text(p.title, p.requirements)
                        new_reqs = extract_requirements(p.description or "")
                        if new_reqs != (p.requirements or []):
                            p.requirements = new_reqs
                            reqs_changed += 1
                        lvl = extract_qualification_level(
                            f"{p.title or ''}\n{p.description or ''}")
                        if lvl != p.education_level:
                            p.education_level = lvl
                            edu_set += 1
                        # Normally the embedding is only stale if its INPUT changed in THIS pass.
                        # `verify_vectors` recomputes regardless — the repair/audit mode for
                        # vectors that drifted from an EARLIER requirements rewrite, where the
                        # stored requirements already match the extractor so nothing looks changed.
                        new_input = posting_embed_text(p.title, p.requirements)
                        if verify_vectors or new_input != old_input or p.embedding is None:
                            vec = _as_list(embed_passage(new_input))
                            if vec is not None and (p.embedding is None
                                                    or _cos(vec, p.embedding) < _SAME):
                                p.embedding, p.embedding_version = vec, EMBED_VERSION
                                vec_changed += 1
                    db.commit()
                break
            except Exception as e:  # noqa: BLE001 — the tunnel drops under load; retry the chunk
                log(f"  chunk {i} attempt {attempt}: {type(e).__name__}; retrying")
                time.sleep(5)
        if (i // CHUNK) % 20 == 0:
            log(f"  {seen}/{total} — reqs {reqs_changed}, edu {edu_set}, vectors {vec_changed}")
    out = {"seen": seen, "requirements_rewritten": reqs_changed,
           "education_levels_set": edu_set, "embeddings_recomputed": vec_changed}
    log(f"DONE: {out}")
    return out


def main(argv: list[str]) -> None:
    min_len, limit, verify = 800, None, False
    for i, a in enumerate(argv):
        if a == "--min-len":
            min_len = int(argv[i + 1])
        elif a == "--limit":
            limit = int(argv[i + 1])
        elif a == "--verify-vectors":
            verify = True
    run(min_len=min_len, limit=limit, verify_vectors=verify)


if __name__ == "__main__":
    main(sys.argv[1:])
