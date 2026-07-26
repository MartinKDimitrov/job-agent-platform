"""Windowed, sharded ATS detection — candidate selection, the shard plan, and the dispatcher
(per-shard isolation + pacing). No network: the detection function is injected."""
from datetime import datetime, timedelta

from sqlalchemy import select

import app.application.usecases.detect_window as dw
from app.application.usecases.detect_window import plan_detect_shards, run_detect_window
from app.data.company_repo import pending_detection_companies, upsert_company
from app.data.db import SessionLocal
from app.data.models import CrawlRun, Company


def _seed(db):
    for i in range(3):                                          # DE: 3 pending candidates
        upsert_company(db, f"DE Co {i}", country="DE", website=f"https://de{i}.example", active=False)
    upsert_company(db, "FR Co", country="FR", website="https://fr.example", active=False)
    upsert_company(db, "Detected", country="DE", website="https://x.example",
                   ats="greenhouse", ats_slug="x")             # already has ATS -> excluded
    upsert_company(db, "No Site", country="DE", active=False)  # no website -> excluded
    db.commit()


def test_pending_selection_excludes_detected_and_siteless():
    with SessionLocal() as db:
        _seed(db)
        names = {e["name"] for e in pending_detection_companies(db)}
    assert {"DE Co 0", "DE Co 1", "DE Co 2", "FR Co"} == names   # only real pending candidates


def test_recheck_window_skips_recently_probed():
    with SessionLocal() as db:
        _seed(db)
        c = db.execute(select(Company).where(Company.name == "FR Co")).scalar_one()
        c.detected_at = datetime.utcnow() - timedelta(days=2)    # probed 2 days ago
        db.commit()
        names = {e["name"] for e in pending_detection_companies(db)}
    assert "FR Co" not in names and "DE Co 0" in names          # recent miss not re-probed


def test_plan_batches_and_spreads_offsets():
    with SessionLocal() as db:
        _seed(db)
        shards = plan_detect_shards(db, batch=2, total_minutes=480)
    labels = [s.label for s in shards]
    assert {"DE#1", "DE#2", "FR"} == set(labels)               # DE 3/batch2 -> #1,#2; FR single
    by = {s.label: s for s in shards}
    assert [len(by[f"DE#{i}"].entries) for i in (1, 2)] == [2, 1]
    offs = [s.offset_min for s in shards]
    assert offs == sorted(offs) and offs[0] == 0.0 and all(0 <= o <= 480 for o in offs)


def test_window_runs_every_shard_isolated_and_paced():
    with SessionLocal() as db:
        _seed(db)

    seen = []
    def fake_detect(entries):
        seen.append(tuple(e["name"] for e in entries))
        if any(e["name"] == "FR Co" for e in entries):
            raise RuntimeError("FR discovery down")             # one shard fails
        return {"found": 1, "missed": len(entries) - 1, "skipped": 0}

    slept = []
    start = datetime(2026, 7, 26, 0, 0, 0)
    res = run_detect_window(SessionLocal, batch=2, total_minutes=480, detect_fn=fake_detect,
                            now=start, clock=lambda: start, sleep=lambda s: slept.append(s))

    assert res["failed"] == 1 and res["ok"] == res["shards"] - 1
    fr = next(r for r in res["results"] if r["shard"] == "FR")
    assert fr["ok"] is False
    assert slept == sorted(slept) and len(slept) == res["shards"] - 1   # offset-0 shard no sleep

    with SessionLocal() as db:
        kinds = {k for (k,) in db.execute(
            select(CrawlRun.kind).where(CrawlRun.kind.like("detect:%")))}
        fr_run = db.execute(select(CrawlRun).where(CrawlRun.kind == "detect:FR")).scalar_one()
    assert {"detect:DE#1", "detect:DE#2", "detect:FR"} <= kinds
    assert fr_run.ok is False
