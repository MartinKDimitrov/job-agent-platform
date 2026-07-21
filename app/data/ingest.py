"""Persistence of fetched postings, with two dedup layers (agent A3).

1. content_hash (URL-based) — the same source seen again;
2. cross-source (app.domain.dedup): same normalized employer + same/near-identical title, so a
   job fetched from dev.bg AND JobTiger AND an ATS board lands as ONE posting. When the incoming
   duplicate comes from an ATS (canonical apply URL — agent A5), the stored posting's apply_url
   is upgraded to it.

The cross-source index is built in memory per call (no schema change; a persisted dedup_key
arrives with Alembic — ROADMAP step 35).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.entities import RawPosting
from ..domain.dedup import normalize_company, similar_titles
from .models import Posting


def ingest(db: Session, postings: list[RawPosting], source_id: int | None = None) -> dict:
    """Upsert RawPostings into the Posting table. Returns {added, skipped, deduped}."""
    added = skipped = deduped = 0
    # index of existing postings by normalized company, for the cross-source check
    by_company: dict[str, list[Posting]] = {}
    for post in db.execute(select(Posting)).scalars().all():
        by_company.setdefault(normalize_company(post.company), []).append(post)

    for rp in postings:
        chash = rp.content_hash()
        if db.execute(select(Posting.id).where(Posting.content_hash == chash)).first():
            skipped += 1
            continue
        # cross-source duplicate? (same employer, same/near title, different URL)
        dup = None
        norm_co = normalize_company(rp.company)
        if norm_co:
            for cand in by_company.get(norm_co, []):
                if similar_titles(rp.title, cand.title):
                    dup = cand
                    break
        if dup is not None:
            deduped += 1
            # an ATS listing carries the canonical apply URL — upgrade the stored posting
            if rp.source_kind == "ats_api" and rp.apply_url and rp.apply_url != dup.apply_url:
                dup.apply_url = rp.apply_url
            continue
        post = Posting(
            title=rp.title, company=rp.company, url=rp.url, apply_url=rp.apply_url,
            location=rp.location, description=rp.description, requirements=None,
            content_hash=chash, source_id=source_id,
        )
        db.add(post)
        by_company.setdefault(norm_co, []).append(post)   # catch dups within the same batch too
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped, "deduped": deduped}
