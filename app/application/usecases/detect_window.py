"""Windowed, sharded ATS detection — the same shard model as the nightly ingest, applied to
the heavier discovery process (careers-page discovery + ATS probing, ~20–40 requests/company).

A full re-detection over thousands of companies is far too heavy to run as one blocking pass —
and if it dies mid-run the batch is lost. So we shard the pending-detection candidates by
country (big countries sub-batched, smaller than ingest since each company is costlier) and
pace the shards across the nightly window. Each shard is isolated: its own CrawlRun
(kind='detect:<label>') and its own error boundary, so one bad shard never stops the crawl.

Candidates come from the registry: companies with no supported ATS yet, a website to probe,
and not probed within the recheck window. `detect_companies --largecap/--eu` seeds new
candidates into the registry; this crawl then converts them, sharded and paced.

Entry: `python -m app.jobs detect_window` (one cron line; the process paces itself). sleep/clock
are injected so tests exercise the pacing without waiting; `detect_fn` is injected likewise.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ...core.config import settings
from ...data.company_repo import detection_countries, pending_detection_companies
from ...data.metrics_repo import record_run
from ..run_stats import RunStats
from .ingest_window import window_minutes           # shared nightly-window length

log = logging.getLogger(__name__)

_TAIL_MIN = 20      # leave the last shard time to finish inside the window


@dataclass
class DetectShard:
    label: str                                       # "DE" | "DE#2"
    offset_min: float = 0.0
    entries: list = field(default_factory=list)      # candidate dicts for this batch


def plan_detect_shards(db: Session, *, batch: int | None = None,
                       total_minutes: int | None = None) -> list[DetectShard]:
    """Ordered shard plan for detection: one shard per country (sub-batched into `batch`-sized
    pieces), offsets spread across the window. Pure/testable — reads pending candidates, no
    network."""
    batch = batch or settings.detect_shard_batch
    total = total_minutes or window_minutes()
    shards: list[DetectShard] = []
    for country in detection_countries(db):
        entries = pending_detection_companies(db, country=country)
        if not entries:
            continue
        n_batches = (len(entries) + batch - 1) // batch
        for i in range(n_batches):
            lbl = country if n_batches == 1 else f"{country}#{i + 1}"
            shards.append(DetectShard(label=lbl, entries=entries[i * batch:(i + 1) * batch]))
    usable = max(total - _TAIL_MIN, 1)
    n = len(shards)
    for i, sh in enumerate(shards):
        sh.offset_min = (i * usable / (n - 1)) if n > 1 else 0.0
    return shards


def _default_detect_fn(entries: list[dict]) -> dict:
    from ...tools.detect_companies import run_entries
    return run_entries(entries, force=False)          # own session, commits per company


def _run_shard(session_factory, shard: DetectShard, detect_fn) -> dict:
    """Run one detection shard in isolation: its work, then its own CrawlRun. Any failure is
    recorded and swallowed so the window keeps going."""
    started = datetime.utcnow()
    stats = RunStats()
    kind = f"detect:{shard.label}"[:32]
    try:
        res = detect_fn(shard.entries)
        stats.add(found=res.get("found", 0), missed=res.get("missed", 0),
                  skipped=res.get("skipped", 0))
        with session_factory() as db:
            record_run(db, kind, stats, started, ok=True)
        return {"shard": shard.label, "ok": True, **res}
    except Exception as e:  # noqa: BLE001 — one shard must never take down the window
        log.warning("detect shard %s failed: %s", shard.label, e)
        try:
            with session_factory() as db:
                record_run(db, kind, stats, started, ok=False, error=str(e))
        except Exception:  # noqa: BLE001
            pass
        return {"shard": shard.label, "ok": False, "error": str(e)[:200]}


def run_detect_window(session_factory, *, batch: int | None = None,
                      total_minutes: int | None = None, detect_fn=_default_detect_fn,
                      now: datetime | None = None, sleep=time.sleep, clock=None,
                      guard: bool = True) -> dict:
    """Dispatch the detection window: plan country shards, run each at its offset, isolated.
    `guard` skips the run if a previous detection window is still in progress."""
    from .window_guard import acquire_window, release_window
    total = total_minutes or window_minutes()
    start = now or datetime.utcnow()
    clock = clock or datetime.utcnow
    marker = acquire_window(session_factory, "detect_window", now=start) if guard else None
    if guard and marker is None:
        log.warning("detect_window already running — skipping this start")
        return {"skipped": True, "shards": 0, "ok": 0, "failed": 0, "results": []}
    try:
        with session_factory() as db:
            shards = plan_detect_shards(db, batch=batch, total_minutes=total)
        log.info("detect window: %d shards across %d min", len(shards), total)
        results = []
        for sh in shards:
            wait = (start + timedelta(minutes=sh.offset_min) - clock()).total_seconds()
            if wait > 0:
                sleep(wait)
            results.append(_run_shard(session_factory, sh, detect_fn))
        ok = sum(1 for r in results if r.get("ok"))
        summary = RunStats()
        summary.add(shards=len(shards), shards_ok=ok, shards_failed=len(results) - ok)
        release_window(session_factory, marker, ok=True, stats=summary)
        return {"shards": len(shards), "ok": ok, "failed": len(results) - ok, "results": results}
    except Exception as e:  # noqa: BLE001 — release the marker before propagating
        release_window(session_factory, marker, ok=False, error=str(e))
        raise
