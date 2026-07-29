"""Persistence of fetched postings, with two dedup layers (agent A3) + liveness signals:
every posting a fetch shows gets its `last_seen_at` touched (takedown detection keys off
it), and a retired posting that a source shows again resurrects — unless it's past the
age cutoff (the owner's hard >1 month rule wins over reposts).

1. content_hash (URL-based) — the same source seen again;
2. cross-source (app.domain.dedup): same normalized employer + same/near-identical title, so a
   job fetched from dev.bg AND JobTiger AND an ATS board lands as ONE posting. When the incoming
   duplicate comes from an ATS (canonical apply URL — agent A5), the stored posting's apply_url
   is upgraded to it.

The cross-source index is built in memory per call (no schema change; a persisted dedup_key
arrives with Alembic — ROADMAP step 35).
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..domain.entities import RawPosting
from ..domain.dedup import normalize_company, similar_titles
from ..domain.salary import parse_salary
from .models import Posting


def _touch(post: Posting, now: datetime) -> None:
    """A fetch just showed this posting: refresh liveness, resurrect if it was retired
    early (failed fetch / repost) — but never past the hard age cutoff."""
    post.last_seen_at = now
    if not post.is_live and settings.posting_max_age_days:
        cutoff = now - timedelta(days=settings.posting_max_age_days)
        # a same-batch row isn't flushed yet (first_seen still None) — it's brand new
        if (post.posted_at or post.first_seen or now) >= cutoff:
            post.is_live = True


def _existing_by_hash(db: Session, chash: str) -> Posting | None:
    return db.execute(
        select(Posting).where(Posting.content_hash == chash).limit(1)).scalars().first()


# Aggregator links that bounce through the aggregator's own site instead of the employer's page.
# Jooble's free API only ever returns a jooble.org/away|desc link (the real apply URL is not in the
# response) — so when the SAME job also arrives from a direct source, we prefer that direct link.
_INDIRECT_HOSTS = ("jooble.org",)


def _is_indirect(url: str | None) -> bool:
    return bool(url) and any(h in url for h in _INDIRECT_HOSTS)


def ingest(db: Session, postings: list[RawPosting], source_id: int | None = None) -> dict:
    """Upsert RawPostings into the Posting table. Returns {added, skipped, deduped}."""
    added = skipped = deduped = 0
    now = datetime.utcnow()
    # Cross-source check index — but only load the CANDIDATE rows: postings whose normalized
    # company matches one in THIS batch. The old code scanned the whole table on every call
    # (O(n) per ~50-posting page — crippling at 100k+ rows and under parallel writers). With
    # norm_company indexed, this is a small, bounded lookup.
    batch_norms = {n for n in (normalize_company(rp.company) for rp in postings) if n}
    by_company: dict[str, list[Posting]] = {}
    if batch_norms:
        for post in db.execute(
                select(Posting).where(Posting.norm_company.in_(batch_norms))).scalars().all():
            by_company.setdefault(post.norm_company, []).append(post)

    # Exact-dedup layer, batched the same way: ONE query for every content_hash in this page
    # instead of a per-posting SELECT. The per-row _existing_by_hash was the bulk drain's real
    # bottleneck — ~200 sequential round-trips/page over the flaky staging tunnel (~33s/wave
    # measured); one IN(...) lookup collapses that to a single round-trip.
    batch_hashes = {rp.content_hash() for rp in postings}
    by_hash: dict[str, Posting] = {}
    if batch_hashes:
        for post in db.execute(
                select(Posting).where(Posting.content_hash.in_(batch_hashes))).scalars().all():
            by_hash[post.content_hash] = post

    for rp in postings:
        chash = rp.content_hash()
        existing = by_hash.get(chash)
        if existing is not None:
            # cheap backfill: rows ingested before posted_at existed learn their source date
            # the next time the source shows them (age filter needs it)
            if existing.posted_at is None and rp.posted_at is not None:
                existing.posted_at = rp.posted_at.replace(tzinfo=None)
            _touch(existing, now)
            skipped += 1
            continue
        # age gate: never bring in a brand-new posting the source dates older than the cutoff
        # (owner rule: no ads over ~2 months). Unknown-age postings (no posted_at) still enter.
        if rp.posted_at is not None and settings.posting_max_ingest_age_days:
            cutoff = now - timedelta(days=settings.posting_max_ingest_age_days)
            if rp.posted_at.replace(tzinfo=None) < cutoff:
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
            # keep the most direct apply URL for the stored posting: an ATS canonical link, or any
            # employer link in place of an aggregator redirect (jooble.org points at its own page,
            # not the employer's). Order-independent — the direct link wins whichever arrives first.
            if rp.apply_url and rp.apply_url != dup.apply_url and (
                    rp.source_kind == "ats_api"
                    or (_is_indirect(dup.apply_url) and not _is_indirect(rp.apply_url))):
                dup.apply_url = rp.apply_url
            _touch(dup, now)
            continue
        # clamp to column limits — Postgres rejects the whole INSERT batch otherwise
        # (a long Ashby multi-location string killed a live ingest; SQLite doesn't enforce)
        sal = parse_salary(f"{rp.title or ''}\n{rp.description or ''}")
        post = Posting(
            title=(rp.title or "")[:512], company=(rp.company or "")[:255],
            norm_company=norm_co,
            url=rp.url, apply_url=rp.apply_url,
            location=(rp.location or "")[:255], description=rp.description, requirements=None,
            posted_at=(rp.posted_at.replace(tzinfo=None) if rp.posted_at else None),
            last_seen_at=now, content_hash=chash, source_id=source_id,
            salary_min=sal["min"] if sal else None,
            salary_max=sal["max"] if sal else None,
            salary_currency=sal["currency"] if sal else None,
            salary_period=sal["period"] if sal else None,
            salary_raw=sal["raw"][:64] if sal else None,
        )
        # Insert inside a SAVEPOINT: with content_hash UNIQUE, a concurrent writer (parallel
        # aggregators) may have inserted this same posting between our SELECT above and now.
        # The savepoint lets that one racing row roll back without losing the rest of the batch;
        # we then fetch the winner and touch it, so nothing is dropped or double-counted.
        try:
            with db.begin_nested():
                db.add(post)
                db.flush()
        except IntegrityError:
            existing = _existing_by_hash(db, chash)          # the concurrent winner
            if existing is not None:
                _touch(existing, now)
            skipped += 1
            continue
        by_company.setdefault(norm_co, []).append(post)   # catch dups within the same batch too
        by_hash[chash] = post                              # and exact re-hashes later in the batch
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped, "deduped": deduped}
