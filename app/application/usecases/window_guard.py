"""Overlap guard for the windowed crawls (ingest_window / detect_window).

A nightly window can run for hours; if the previous night's run is somehow still going when the
next one starts, they'd compete for the same hosts and DB. The guard is a lightweight DB marker
(a CrawlRun row with finished_at IS NULL = "running"): a new window acquires it only when no
LIVE marker of that kind exists, and releases it on completion. Portable — Postgres in prod,
SQLite in tests — and safe for the single-scheduler cron case this protects.

A marker older than `stale_hours` is treated as a crashed run and ignored, so one crash never
blocks the window forever.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from ...data.models import CrawlRun

log = logging.getLogger(__name__)

STALE_HOURS = 12       # a running-marker older than this = a crashed run, not a live one


def acquire_window(session_factory, kind: str, *, stale_hours: int = STALE_HOURS,
                   now: datetime | None = None) -> int | None:
    """Claim the window for `kind`. Returns the marker id, or None when another run holds it
    (a non-stale, unfinished marker of the same kind already exists)."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=stale_hours)
    with session_factory() as db:
        live = db.execute(select(CrawlRun.id).where(
            CrawlRun.kind == kind, CrawlRun.finished_at.is_(None),
            CrawlRun.started_at >= cutoff).limit(1)).scalar_one_or_none()
        if live is not None:
            return None
        marker = CrawlRun(kind=kind, started_at=now, finished_at=None, ok=False)
        db.add(marker)
        db.commit()
        db.refresh(marker)
        return marker.id


def release_window(session_factory, marker_id: int | None, *, ok: bool = True,
                   stats=None, error: str = "") -> None:
    """Finish the window marker (sets finished_at) so the next run can acquire it."""
    if marker_id is None:
        return
    with session_factory() as db:
        marker = db.get(CrawlRun, marker_id)
        if marker is None:
            return
        marker.finished_at = datetime.utcnow()
        marker.ok = ok
        marker.error = (error or "")[:2000]
        if stats is not None:
            marker.stats = stats.to_dict()
        db.commit()
