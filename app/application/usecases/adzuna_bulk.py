"""Adzuna bulk pull — draining ALL professions, in resumable batches.

We serve any profession, not just the test profiles, so we can't drive Adzuna by role terms:
we drain it by its own taxonomy. Adzuna partitions every posting into ~30 CATEGORIES; the plan
is CATEGORY × COUNTRY = one slice per (country, category), each an independent, resumable cursor
(``AdzunaPull``). A run walks slices, fetching one search page at a time, persisting, then
committing the advanced cursor after EVERY page — so progress is durable to the ~50-posting page,
checkable at any moment, and a killed run resumes exactly where it stopped.

The real constraint is the trial CALL quota, so a run takes a ``call_budget`` and spreads it:
slices are visited least-pulled-first and capped at ``pages_per_slice`` per run, so the budget
fans out across professions/countries instead of sinking into one huge category (IT alone is
~28k in DE). Nightly cron just calls ``run_bulk`` again; the cursors carry the state.
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import func, select

from ...data.models import AdzunaPull
from ...data.sources import adzuna
from .search import persist_postings

COUNTRIES = adzuna.COUNTRIES                 # de/fr/it/gb/es/nl/pl
RESULTS_PER_PAGE = adzuna.RESULTS_PER_PAGE   # 50
DEFAULT_CALL_BUDGET = 200                    # Adzuna calls per run — spread across slices
DEFAULT_PAGES_PER_SLICE = 20                 # cap per slice per run -> budget fans out


def ensure_slices(session_factory, countries=COUNTRIES) -> int:
    """Seed one AdzunaPull row per (country, category) from Adzuna's live taxonomy. Idempotent:
    existing slices are left untouched (labels refreshed). Returns the slice count."""
    created = 0
    for country in countries:
        cats = adzuna.categories(country)
        if not cats:
            continue                          # keys unset or API down -> skip, retry next run
        with session_factory() as db:
            existing = {c for (c,) in db.execute(
                select(AdzunaPull.category).where(AdzunaPull.country == country)).all()}
            for tag, label in cats:
                if not tag:
                    continue
                if tag in existing:
                    row = db.execute(select(AdzunaPull).where(
                        AdzunaPull.country == country, AdzunaPull.category == tag)).scalar_one()
                    row.label = label or row.label
                else:
                    db.add(AdzunaPull(country=country, category=tag, label=label or ""))
                    created += 1
            db.commit()
    return created


def run_bulk(session_factory, *, call_budget: int = DEFAULT_CALL_BUDGET,
             pages_per_slice: int = DEFAULT_PAGES_PER_SLICE,
             results_per_page: int = RESULTS_PER_PAGE, countries=COUNTRIES,
             sleep=time.sleep) -> dict:
    """Drain up to ``call_budget`` pages across not-yet-done slices, least-pulled-first, at most
    ``pages_per_slice`` per slice this run. Commits after every page (durable cursor). Returns a
    run summary; progress persists in AdzunaPull for the board/status."""
    if not adzuna._configured():
        return {"configured": False, "calls": 0, "added": 0, "slices_touched": 0}

    ensure_slices(session_factory, countries)

    with session_factory() as db:
        pending = db.execute(
            select(AdzunaPull.id).where(AdzunaPull.done.is_(False),
                                        AdzunaPull.country.in_(countries))
            .order_by(AdzunaPull.pulled.asc(), AdzunaPull.id.asc())).scalars().all()

    calls = added = touched = 0
    for slice_id in pending:
        if calls >= call_budget:
            break
        pages_this_slice = 0
        touched_this = False
        while calls < call_budget and pages_this_slice < pages_per_slice:
            with session_factory() as db:
                row = db.get(AdzunaPull, slice_id)
                if row is None or row.done:
                    break
                country, category, page = row.country, row.category, row.next_page
            posts, total = adzuna.fetch_page(country, page, category=category,
                                             results_per_page=results_per_page)
            calls += 1
            pages_this_slice += 1
            with session_factory() as db:
                row = db.get(AdzunaPull, slice_id)
                res = persist_postings(db, posts)
                row.pulled += res["added"]
                row.total = total or row.total
                row.next_page = page + 1
                # A short page (or empty) means we've drained this slice's window.
                if len(posts) < results_per_page:
                    row.done = True
                row.updated_at = datetime.utcnow()
                db.commit()
                added += res["added"]
                done = row.done
            touched_this = True
            if done:
                break
            sleep(adzuna.CALL_DELAY)
        if touched_this:
            touched += 1
    return {"configured": True, "calls": calls, "added": added, "slices_touched": touched}


def status(db) -> dict:
    """Snapshot for the board / CLI: overall %, per-country and per-slice progress."""
    rows = db.execute(select(AdzunaPull).order_by(
        AdzunaPull.country.asc(), AdzunaPull.pulled.desc())).scalars().all()
    pulled = sum(r.pulled for r in rows)
    est_total = sum(r.total for r in rows)
    done = sum(1 for r in rows if r.done)
    by_country: dict[str, dict] = {}
    for r in rows:
        c = by_country.setdefault(r.country.upper(),
                                  {"pulled": 0, "total": 0, "slices": 0, "done": 0})
        c["pulled"] += r.pulled
        c["total"] += r.total
        c["slices"] += 1
        c["done"] += 1 if r.done else 0
    return {
        "slices": len(rows),
        "slices_done": done,
        "pulled": pulled,
        "est_total": est_total,
        "pct": round(100 * pulled / est_total, 1) if est_total else 0.0,
        "by_country": by_country,
        "slices_detail": [
            {"country": r.country.upper(), "category": r.category, "label": r.label,
             "pulled": r.pulled, "total": r.total, "next_page": r.next_page, "done": r.done,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows],
    }
