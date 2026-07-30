"""Deep bulk DRAIN of the keyword-less aggregator feeds (Careerjet / Jooble) — the analogue of the
Adzuna category×country drain, but the slice here is (source, locale) and the firehose is each
locale's FEED (no keyword), paginated as deep as it goes. One page per API call, cursor advanced
and committed after every page (``AggregatorDrain``), so progress is durable and a killed run
resumes exactly where it stopped.

Careerjet is generous → drain all 8 markets fully. Jooble's free tier is 500 requests TOTAL, so
its drain is budget-capped and focused on the key markets.

    python -m app.jobs careerjet_drain [call_budget]
    python -m app.jobs jooble_drain [call_budget]
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import select

from ...data.models import AggregatorDrain
from ...data.sources import careerjet, jooble, eures
from .search import persist_postings

CALL_DELAY = 0.4
# Careerjet scales cleanly with concurrency (measured 2026-07-29: K=8 -> 10.8 req/s / ~216 jobs/s,
# 0 failures, no visible rate limit — unlike Adzuna which 429s past K=4). With only 8 locales a wave
# fetches them all in parallel, one page deeper each round. Jooble stays budget-bounded either way.
DEFAULT_CONCURRENCY = int(os.getenv("AGG_CONCURRENCY", "8"))

# per source: the locale slices + a one-page fetch(locale, page) -> [RawPosting]
_JOOBLE_LOCATIONS = ["", "Bulgaria", "Germany", "United Kingdom", "France", "Netherlands",
                     "Spain", "Poland", "Austria", "Italy"]
_SOURCES = {
    "careerjet": {
        "slices": list(careerjet.LOCALES),
        "configured": careerjet._configured,
        "fetch": lambda loc, page: careerjet.fetch(countries=[loc], search_terms=None,
                                                    start_page=page, pages=1),
    },
    "jooble": {
        "slices": _JOOBLE_LOCATIONS,
        "configured": jooble._configured,
        "fetch": lambda loc, page: jooble.fetch(search_terms=None, location=loc,
                                                start_page=page, pages=1),
    },
    # EURES: the official EU portal (anonymous, no key). Slice = country; an empty page retires it.
    # Profiled 2026-07-30: ~42 jobs/page, ~900ms, scales to K=4 (plateaus after), 0 rate limits.
    "eures": {
        "slices": list(eures.EURES_COUNTRIES),
        "configured": lambda: True,
        "fetch": lambda loc, page: eures.fetch_page(loc, page),
    },
}
DEFAULT_BUDGET = {"careerjet": 4000, "jooble": 300, "eures": 2000}
# EURES server caps useful parallelism ~4 (K=8 gives no more throughput); keep its waves at 4.
_CONCURRENCY_OVERRIDE = {"eures": 4}


def ensure_slices(db, source: str) -> None:
    have = {r.locale for r in db.execute(
        select(AggregatorDrain).where(AggregatorDrain.source == source)).scalars()}
    for loc in _SOURCES[source]["slices"]:
        if loc not in have:
            db.add(AggregatorDrain(source=source, locale=loc))
    db.commit()


def run_drain(source: str, session_factory, *, call_budget: int | None = None,
              sleep=time.sleep) -> dict:
    """Drain `source` feeds page-by-page within `call_budget` API calls, least-pulled slice first
    (so the budget fans out across markets). An empty page retires its slice (feed exhausted)."""
    cfg = _SOURCES[source]
    call_budget = DEFAULT_BUDGET[source] if call_budget is None else call_budget
    if not cfg["configured"]():
        return {"source": source, "calls": 0, "added": 0, "note": "api key not set"}
    calls = added = 0
    with session_factory() as db:
        ensure_slices(db, source)
        while calls < call_budget:
            row = db.execute(
                select(AggregatorDrain).where(AggregatorDrain.source == source,
                                              AggregatorDrain.done.is_(False))
                .order_by(AggregatorDrain.pulled)).scalars().first()
            if row is None:
                break                                    # every slice exhausted
            posts = cfg["fetch"](row.locale, row.next_page)
            calls += 1
            if not posts:
                row.done = True                          # empty page -> feed exhausted
            else:
                res = persist_postings(db, posts)
                row.pulled += res["added"]
                added += res["added"]
                row.next_page += 1
            row.updated_at = datetime.utcnow()
            db.commit()
            if calls % 25 == 0:
                print(f"[{source}] {calls} calls, {added} added", flush=True)
            sleep(CALL_DELAY)
    print(f"DONE {source}: {calls} calls, {added} added", flush=True)
    return {"source": source, "calls": calls, "added": added}


def run_drain_concurrent(source: str, session_factory, *, call_budget: int | None = None,
                         concurrency: int = DEFAULT_CONCURRENCY, log=print) -> dict:
    """Concurrent analogue of run_drain: each wave fetches up to ``concurrency`` distinct
    least-pulled slices' next page IN PARALLEL, then persists the whole wave through ONE db
    session/commit (tunnel-safe single writer). Resumable via the same AggregatorDrain cursors; an
    empty page retires its slice. Careerjet has no visible rate limit up to K=8, so this is ~8x the
    sequential path; Jooble stays bounded by ``call_budget`` (free-tier 500-total cap)."""
    cfg = _SOURCES[source]
    call_budget = DEFAULT_BUDGET[source] if call_budget is None else call_budget
    if concurrency == DEFAULT_CONCURRENCY:            # honour a per-source cap unless caller overrode
        concurrency = _CONCURRENCY_OVERRIDE.get(source, concurrency)
    if not cfg["configured"]():
        return {"source": source, "calls": 0, "added": 0, "note": "api key not set"}
    with session_factory() as db:
        ensure_slices(db, source)
    calls = added = waves = 0
    while calls < call_budget:
        with session_factory() as db:
            rows = db.execute(
                select(AggregatorDrain).where(AggregatorDrain.source == source,
                                              AggregatorDrain.done.is_(False))
                .order_by(AggregatorDrain.pulled).limit(concurrency)).scalars().all()
            wave = [(r.id, r.locale, r.next_page) for r in rows]
        if not wave:
            break                                        # every slice exhausted

        def _fetch(task):
            sid, locale, page = task
            try:
                return sid, page, cfg["fetch"](locale, page)
            except Exception as e:                       # noqa: BLE001 — one bad page mustn't kill it
                log(f"[{source}] fetch error {locale} p{page}: {type(e).__name__}")
                return sid, page, None
        with ThreadPoolExecutor(max_workers=len(wave)) as ex:
            results = list(ex.map(_fetch, wave))
        calls += len(results)

        with session_factory() as db:                    # single writer — one tunnel connection
            for sid, page, posts in results:
                row = db.get(AggregatorDrain, sid)
                if row is None or posts is None:
                    continue                             # fetch error: leave cursor, retry later
                if not posts:
                    row.done = True                      # empty page -> feed exhausted
                else:
                    res = persist_postings(db, posts)
                    row.pulled += res["added"]
                    added += res["added"]
                    row.next_page = page + 1
                row.updated_at = datetime.utcnow()
            db.commit()
        waves += 1
        if waves % 5 == 0:
            log(f"[{source}] {calls} calls, {added} added ({waves} waves, K={concurrency})")
    log(f"DONE {source} concurrent: {calls} calls, {added} added")
    return {"source": source, "calls": calls, "added": added, "waves": waves,
            "concurrency": concurrency}


def status(db, source: str) -> dict:
    rows = db.execute(select(AggregatorDrain).where(
        AggregatorDrain.source == source).order_by(AggregatorDrain.pulled.desc())).scalars().all()
    return {"source": source,
            "slices": [{"locale": r.locale, "page": r.next_page, "pulled": r.pulled, "done": r.done}
                       for r in rows],
            "total_pulled": sum(r.pulled for r in rows)}
