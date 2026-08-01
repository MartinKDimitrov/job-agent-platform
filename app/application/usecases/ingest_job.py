"""Scheduled ingest (the WRITE side of DB-first search).

`run_ingest` fetches every fast source plus per-profile targeted queries for ACTIVE users,
persists + enriches (requirements, E5 vector), and records a CrawlRun. It is invoked by:
- the in-app background thread (`start_background_ingester`, INGEST_EVERY_HOURS > 0), and
- cron on the VPS at deploy time: `python -m app.jobs ingest`.

The thread checks the LAST successful ingest run in the DB (not process uptime), so restarts
don't cause refetch storms and a long-stopped dev server catches up immediately on boot.
"""
import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import settings
from ...data.models import CrawlRun, Profile, User
from ...data.activity_repo import get_activity
from ...domain.activity_rules import is_active_for_search
from ...data.metrics_repo import record_run
from ..run_stats import RunStats
from .search import ingest_from_sources

log = logging.getLogger(__name__)

_KIND = "ingest"


def _active_profiles(db: Session, now=None) -> list[Profile]:
    """Profiles of users the daily job would search for — targeted queries follow the same
    gating (found-job / inactivity), so we don't crawl for dormant accounts."""
    now = now or datetime.utcnow()
    out: list[Profile] = []
    for u in db.execute(select(User)).scalars():
        if not is_active_for_search(u, get_activity(db, u.id), now):
            continue
        out.extend(db.execute(select(Profile).where(Profile.user_id == u.id)).scalars())
    return out


def ingest_due(db: Session, every_hours: int, now=None) -> bool:
    """True when the last successful ingest is older than the interval (or never ran)."""
    now = now or datetime.utcnow()
    last = db.execute(
        select(CrawlRun.started_at).where(CrawlRun.kind == _KIND, CrawlRun.ok.is_(True))
        .order_by(CrawlRun.started_at.desc()).limit(1)).scalar_one_or_none()
    return last is None or now - last >= timedelta(hours=every_hours)


def run_ingest(db: Session) -> dict:
    """One full ingest cycle, recorded as a CrawlRun (kind='ingest')."""
    started = datetime.utcnow()
    stats = RunStats()
    try:
        res = ingest_from_sources(db, profiles=_active_profiles(db), stats=stats)
        record_run(db, _KIND, stats, started, ok=True)
        return res
    except Exception as e:  # noqa: BLE001 — record the failure, then re-raise
        db.rollback()
        record_run(db, _KIND, stats, started, ok=False, error=str(e))
        raise


def start_background_ingester(session_factory, every_hours: int | None = None,
                              poll_seconds: int = 600) -> threading.Thread | None:
    """Daemon thread: every `poll_seconds` check the DB; run an ingest when one is due.
    Returns the thread, or None when disabled (every_hours == 0 — tests, cron-managed envs)."""
    every_hours = settings.ingest_every_hours if every_hours is None else every_hours
    if not every_hours:
        return None

    def _loop():
        while True:
            try:
                with session_factory() as db:
                    if ingest_due(db, every_hours):
                        log.info("background ingest starting (every %sh)", every_hours)
                        res = run_ingest(db)
                        log.info("background ingest done: %s", res)
                        # run_ingest invalidated the recall cache — rebuild it here, off the
                        # request path, so the next user search doesn't pay the ~90s reload.
                        from .. import vector_cache
                        vector_cache.warm(db)
            except Exception as e:  # noqa: BLE001 — the thread must survive any source failure
                log.warning("background ingest failed: %s", e)
            time.sleep(poll_seconds)

    thread = threading.Thread(target=_loop, name="ingester", daemon=True)
    thread.start()
    return thread
