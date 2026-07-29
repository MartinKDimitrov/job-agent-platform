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
import time
from datetime import datetime

from sqlalchemy import select

from ...data.models import AggregatorDrain
from ...data.sources import careerjet, jooble
from .search import persist_postings

CALL_DELAY = 0.4

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
}
DEFAULT_BUDGET = {"careerjet": 4000, "jooble": 300}


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


def status(db, source: str) -> dict:
    rows = db.execute(select(AggregatorDrain).where(
        AggregatorDrain.source == source).order_by(AggregatorDrain.pulled.desc())).scalars().all()
    return {"source": source,
            "slices": [{"locale": r.locale, "page": r.next_page, "pulled": r.pulled, "done": r.done}
                       for r in rows],
            "total_pulled": sum(r.pulled for r in rows)}
