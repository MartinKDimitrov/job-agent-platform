"""Overlap guard for the windowed crawls: only one live window per kind, stale markers ignored,
and the dispatcher skips when a previous run is still in progress."""
from datetime import datetime, timedelta

import app.application.usecases.ingest_window as iw
from app.application.usecases.ingest_window import run_ingest_window
from app.application.usecases.window_guard import STALE_HOURS, acquire_window, release_window
from app.data.db import SessionLocal
from app.data.models import CrawlRun


def test_acquire_blocks_second_then_frees_on_release():
    a = acquire_window(SessionLocal, "ingest_window")
    assert a is not None
    assert acquire_window(SessionLocal, "ingest_window") is None      # already held
    assert acquire_window(SessionLocal, "detect_window") is not None  # other kind independent
    release_window(SessionLocal, a, ok=True)
    b = acquire_window(SessionLocal, "ingest_window")
    assert b is not None and b != a                                   # freed -> re-acquirable


def test_stale_marker_is_ignored():
    old = datetime.utcnow() - timedelta(hours=STALE_HOURS + 1)
    with SessionLocal() as db:
        db.add(CrawlRun(kind="ingest_window", started_at=old, finished_at=None, ok=False))
        db.commit()
    assert acquire_window(SessionLocal, "ingest_window") is not None   # crashed run doesn't block


def test_window_skips_when_a_run_is_already_live(monkeypatch):
    now = datetime(2026, 7, 26, 0, 0, 0)
    acquire_window(SessionLocal, "ingest_window", now=now)            # a run is in progress
    ran = []
    monkeypatch.setattr(iw, "_run_shard", lambda *a, **k: ran.append(1) or {"ok": True})
    res = run_ingest_window(SessionLocal, total_minutes=480, profiles_fn=lambda db: (),
                            now=now, clock=lambda: now, sleep=lambda s: None)
    assert res.get("skipped") is True and res["shards"] == 0 and ran == []
