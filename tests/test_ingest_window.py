"""Windowed, sharded ingest — the shard plan (batching + offsets) and the dispatcher
(per-shard isolation + pacing). No network: the shard work functions are monkeypatched."""
from datetime import datetime

from sqlalchemy import select

import app.application.usecases.ingest_window as w
from app.application.usecases.ingest_window import plan_shards, run_ingest_window
from app.data.company_repo import upsert_company
from app.data.db import SessionLocal
from app.data.models import CrawlRun


def _seed(db):
    for i in range(5):                                   # DE: 5 boards
        upsert_company(db, f"DE Co {i}", country="DE", ats="greenhouse", ats_slug=f"deco{i}")
    upsert_company(db, "FR Co", country="FR", ats="lever", ats_slug="frco")   # FR: 1
    upsert_company(db, "BG Co", country="BG", ats="ashby", ats_slug="bgco")   # BG: 1


def test_plan_batches_countries_and_spreads_offsets():
    with SessionLocal() as db:
        _seed(db)
        shards = plan_shards(db, batch=2, total_minutes=480)
    labels = [s.label for s in shards]
    assert labels[0] == "global" and labels[-1] == "finalize"
    # DE (5 boards / batch 2) -> three sub-shards; single-batch countries keep the bare code
    assert {"DE#1", "DE#2", "DE#3", "FR", "BG"} <= set(labels)
    by = {s.label: s for s in shards}
    assert [len(by[f"DE#{i}"].boards) for i in (1, 2, 3)] == [2, 2, 1]
    offs = [s.offset_min for s in shards]
    assert offs == sorted(offs) and offs[0] == 0.0        # paced, starts at window open
    assert all(0 <= o <= 480 for o in offs)
    assert by["finalize"].offset_min >= 480 - 30          # finalize reserved for the tail


def test_window_runs_every_shard_isolated_and_paced(monkeypatch):
    with SessionLocal() as db:
        _seed(db)

    calls = []
    monkeypatch.setattr(w, "run_ingest_global",
                        lambda db, profiles=(), stats=None: (calls.append("global") or {"added": 1}))
    monkeypatch.setattr(w, "run_ingest_maintenance",
                        lambda db, stats=None: (calls.append("finalize") or {"enriched": 0}))

    def fake_boards(db, boards, stats=None):
        calls.append(("boards", len(boards)))
        if any(slug == "frco" for _, slug, _ in boards):
            raise RuntimeError("FR board down")           # one shard fails mid-window
        return {"added": len(boards)}
    monkeypatch.setattr(w, "run_ingest_shard_boards", fake_boards)

    slept = []
    start = datetime(2026, 7, 26, 0, 0, 0)
    res = run_ingest_window(SessionLocal, batch=2, total_minutes=480,
                            profiles_fn=lambda db: (), now=start, clock=lambda: start,
                            sleep=lambda s: slept.append(s))

    assert "global" in calls and "finalize" in calls      # fixed + finalize shards ran
    assert res["failed"] == 1 and res["ok"] == res["shards"] - 1   # FR failed, rest fine
    fr = next(r for r in res["results"] if r["shard"] == "FR")
    assert fr["ok"] is False
    # paced: the offset-0 shard runs immediately (no sleep), the rest sleep in ascending order
    assert slept == sorted(slept) and len(slept) == res["shards"] - 1

    with SessionLocal() as db:                            # every shard logged its own CrawlRun
        kinds = {k for (k,) in db.execute(
            select(CrawlRun.kind).where(CrawlRun.kind.like("ingest:%")))}
        fr_run = db.execute(select(CrawlRun).where(CrawlRun.kind == "ingest:FR")).scalar_one()
    assert {"ingest:global", "ingest:finalize", "ingest:FR", "ingest:DE#1"} <= kinds
    assert fr_run.ok is False                             # the failure recorded, not lost
