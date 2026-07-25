"""Windowed, sharded ingest — the scalable replacement for the single monolithic daily crawl.

Why: as the company registry grows to thousands of boards, one big `run_ingest` gets long and
becomes a single point of failure — if it dies mid-run the whole cycle is lost. Instead we cut
the crawl into independent shards (one per country, big countries sub-batched) plus a 'global'
shard for the fixed non-registry feeds, and pace them across a nightly window (default
00:00–08:00). Each shard:
  - is its own isolated unit — its failure records a failed CrawlRun and the window continues;
  - has its own start offset spread across the window, so load is distributed, not bursty.
A single 'finalize' shard at the end runs the global upkeep (enrich/annotate/retire/dedup) once.

Entry point: `python -m app.jobs ingest_window` (one cron line at the window start). The process
sleeps between shards to hit their offsets — sleep/clock are injected so tests never really wait.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ...core.config import settings
from ...data.company_repo import board_countries
from ...data.metrics_repo import record_run
from ..run_stats import RunStats
from .search import (registry_boards, run_ingest_global, run_ingest_maintenance,
                     run_ingest_shard_boards)

log = logging.getLogger(__name__)

_FINALIZE_TAIL_MIN = 30      # minutes reserved at the window's end for the finalize shard


@dataclass
class Shard:
    label: str                      # "global" | "DE" | "DE#2" | "finalize"
    kind: str                       # "global" | "country" | "finalize"
    offset_min: float = 0.0         # minutes after the window start when this shard runs
    boards: list = field(default_factory=list)   # (ats, slug, name) for country shards


def window_minutes(start_hour: int | None = None, end_hour: int | None = None) -> int:
    """Length of the nightly window in minutes (wraps past midnight, e.g. 22→06 = 8h)."""
    s = settings.ingest_window_start_hour if start_hour is None else start_hour
    e = settings.ingest_window_end_hour if end_hour is None else end_hour
    return ((e - s) % 24 or 24) * 60


def plan_shards(db: Session, *, batch: int | None = None,
                total_minutes: int | None = None) -> list[Shard]:
    """Build the ordered shard plan with start offsets spread across the window. Pure/testable —
    reads board counts from the DB, does no network. One 'global' shard first, then one country
    shard per country (sub-batched into `batch`-sized pieces when a country has many boards),
    then a 'finalize' shard reserved near the window's end."""
    batch = batch or settings.ingest_shard_batch
    total = total_minutes or window_minutes()
    fetch: list[Shard] = [Shard(label="global", kind="global")]
    for country in board_countries(db):
        boards = registry_boards(db, country=country)
        if not boards:
            continue
        n_batches = (len(boards) + batch - 1) // batch
        for i in range(n_batches):
            lbl = country if n_batches == 1 else f"{country}#{i + 1}"
            fetch.append(Shard(label=lbl, kind="country", boards=boards[i * batch:(i + 1) * batch]))
    # spread fetch shards across [0, total - tail]; finalize sits in the reserved tail
    usable = max(total - _FINALIZE_TAIL_MIN, 1)
    n = len(fetch)
    for i, sh in enumerate(fetch):
        sh.offset_min = (i * usable / (n - 1)) if n > 1 else 0.0
    finalize = Shard(label="finalize", kind="finalize",
                     offset_min=float(max(total - _FINALIZE_TAIL_MIN / 2, usable)))
    return fetch + [finalize]


def _run_shard(session_factory, shard: Shard, profiles_fn) -> dict:
    """Run one shard in full isolation: its own session + CrawlRun; any failure is recorded and
    swallowed so the window keeps going."""
    started = datetime.utcnow()
    stats = RunStats()
    kind = f"ingest:{shard.label}"[:32]
    try:
        with session_factory() as db:
            if shard.kind == "global":
                profiles = profiles_fn(db) if profiles_fn else ()
                res = run_ingest_global(db, profiles=profiles, stats=stats)
            elif shard.kind == "finalize":
                res = run_ingest_maintenance(db, stats=stats)
            else:
                res = run_ingest_shard_boards(db, shard.boards, stats=stats)
            record_run(db, kind, stats, started, ok=True)
        return {"shard": shard.label, "ok": True, **res}
    except Exception as e:  # noqa: BLE001 — one shard must never take down the window
        log.warning("ingest shard %s failed: %s", shard.label, e)
        try:
            with session_factory() as db:
                record_run(db, kind, stats, started, ok=False, error=str(e))
        except Exception:  # noqa: BLE001 — even the failure-record must not raise
            pass
        return {"shard": shard.label, "ok": False, "error": str(e)[:200]}


def _default_profiles_fn(db: Session):
    from .ingest_job import _active_profiles
    return _active_profiles(db)


def run_ingest_window(session_factory, *, batch: int | None = None,
                      total_minutes: int | None = None, profiles_fn=_default_profiles_fn,
                      now: datetime | None = None, sleep=time.sleep, clock=None,
                      guard: bool = True) -> dict:
    """Dispatch the whole nightly window: plan shards, then run each at its offset, isolated.
    `sleep`/`clock`/`now` are injected so tests exercise the pacing without waiting. `guard`
    skips the run if a previous ingest window is still in progress (overlap protection)."""
    from .window_guard import acquire_window, release_window
    total = total_minutes or window_minutes()
    start = now or datetime.utcnow()
    clock = clock or datetime.utcnow
    marker = acquire_window(session_factory, "ingest_window", now=start) if guard else None
    if guard and marker is None:
        log.warning("ingest_window already running — skipping this start")
        return {"skipped": True, "shards": 0, "ok": 0, "failed": 0, "results": []}
    try:
        with session_factory() as db:
            shards = plan_shards(db, batch=batch, total_minutes=total)
        log.info("ingest window: %d shards across %d min", len(shards), total)
        results = []
        for sh in shards:
            wait = (start + timedelta(minutes=sh.offset_min) - clock()).total_seconds()
            if wait > 0:
                sleep(wait)
            results.append(_run_shard(session_factory, sh, profiles_fn))
        ok = sum(1 for r in results if r.get("ok"))
        summary = RunStats()
        summary.add(shards=len(shards), shards_ok=ok, shards_failed=len(results) - ok)
        release_window(session_factory, marker, ok=True, stats=summary)
        return {"shards": len(shards), "ok": ok, "failed": len(results) - ok, "results": results}
    except Exception as e:  # noqa: BLE001 — release the marker before propagating
        release_window(session_factory, marker, ok=False, error=str(e))
        raise
