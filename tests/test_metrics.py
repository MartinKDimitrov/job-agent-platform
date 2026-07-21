"""Observability: RunStats collector, CrawlRun recording for daily + Search-now, summary."""
from datetime import datetime

from sqlalchemy import select

import app.adapters.greenhouse as gh
import app.crawl as crawl
import app.routers.profiles as profiles_router
from app.adapters.base import RawPosting
from app.db import SessionLocal
from app.metrics import RunStats, summary, format_summary
from app.models import User, Profile, UserActivity, CrawlRun
from app.jobs import run_daily_digest
from tests.conftest import register, make_profile

SAMPLE = [RawPosting("ats_api", "1", "Senior Android Engineer", "Acme", location="Remote",
                     url="https://x/1", apply_url="https://x/1",
                     description="Requirements:\n- Kotlin")]


def _offline(monkeypatch):
    monkeypatch.setattr(gh, "fetch", lambda token, company_name=None: list(SAMPLE))
    monkeypatch.setattr(crawl, "FAST_SOURCES", [])
    monkeypatch.setattr(crawl, "EXTRA_SOURCES", [])


# ---- RunStats unit ----
def test_runstats_accumulates():
    s = RunStats()
    s.source("greenhouse", fetched=5)
    s.source("greenhouse", fetched=3)
    s.source("dev_bg", error="boom")
    s.add(matched=2)
    s.add(matched=1, added=4)
    d = s.to_dict()
    assert d["sources"]["greenhouse"]["fetched"] == 8
    assert d["sources"]["dev_bg"]["error"] == "boom"
    assert d["totals"] == {"matched": 3, "added": 4}


# ---- daily job records a CrawlRun ----
def test_daily_run_records_crawlrun(monkeypatch):
    _offline(monkeypatch)
    with SessionLocal() as db:
        u = User(email="a@test.local", password_hash="x")
        db.add(u); db.commit(); db.refresh(u)
        db.add(UserActivity(user_id=u.id, last_seen_at=datetime.utcnow()))
        db.add(Profile(user_id=u.id, name="P", target_roles="Android",
                       skills="Kotlin", min_match=0))
        db.commit()
        run_daily_digest(db, boards=[("acme", "Acme")], send=lambda *a: True)
        run = db.execute(select(CrawlRun).where(CrawlRun.kind == "daily")).scalars().one()
        assert run.ok and run.finished_at is not None
        assert run.stats["sources"]["greenhouse"]["fetched"] == 1
        assert run.stats["totals"]["matched"] >= 1
        assert run.stats["totals"]["notified"] == 1


def test_daily_run_records_failure(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr("app.jobs.fetch_all",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom")))
    with SessionLocal() as db:
        try:
            run_daily_digest(db, boards=[("acme", "Acme")], send=lambda *a: True)
        except RuntimeError:
            pass
        run = db.execute(select(CrawlRun)).scalars().one()
        assert run.ok is False and "kaboom" in run.error


# ---- Search-now records a CrawlRun ----
def test_search_now_records_crawlrun(auth_client, monkeypatch):
    _offline(monkeypatch)
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin", min_match=0)
    client.post(f"/profiles/{pid}/search", follow_redirects=False)
    with SessionLocal() as db:
        run = db.execute(select(CrawlRun).where(CrawlRun.kind == "search_now")).scalars().one()
        assert run.ok and run.stats["totals"].get("matched", 0) >= 1


def test_search_now_records_failure(auth_client, monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(profiles_router, "run_search",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad")))
    client, _ = auth_client
    pid = make_profile(client, min_match=0)
    r = client.post(f"/profiles/{pid}/search", follow_redirects=False)
    assert r.status_code == 303                    # still redirects (degrades gracefully)
    with SessionLocal() as db:
        run = db.execute(select(CrawlRun)).scalars().one()
        assert run.ok is False and "bad" in run.error


# ---- summary ----
def test_summary_and_format(monkeypatch):
    _offline(monkeypatch)
    with SessionLocal() as db:
        u = User(email="s@test.local", password_hash="x")
        db.add(u); db.commit(); db.refresh(u)
        db.add(UserActivity(user_id=u.id, last_seen_at=datetime.utcnow()))
        db.add(Profile(user_id=u.id, name="P", target_roles="Android", skills="Kotlin", min_match=0))
        db.commit()
        run_daily_digest(db, boards=[("acme", "Acme")], send=lambda *a: True)
        rows = summary(db)
        assert rows and rows[0]["kind"] == "daily"
        text = format_summary(rows)
        assert "daily" in text and "greenhouse=1" in text
