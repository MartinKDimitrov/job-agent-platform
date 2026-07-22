"""DB-first search: ingest-time enrichment (vectors), staleness scheduling, and the
no-network guarantee of the Search-now read path."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

import app.application.usecases.search as crawl
import app.domain.scoring as scoring
from app.application.usecases.ingest_job import ingest_due, run_ingest
from app.data.db import SessionLocal
from app.data.models import CrawlRun, Posting, Match
from app.domain.entities import RawPosting
from tests.test_crawl import _mock, _make_profile_row


def test_ingest_stores_embedding_and_requirements(monkeypatch):
    _mock(monkeypatch)
    monkeypatch.setattr(crawl, "embed", lambda text: [1.0, 0.0])
    with SessionLocal() as db:
        res = crawl.ingest_from_sources(db)
        assert res["added"] == 2 and res["enriched"] == 2
        for p in db.execute(select(Posting)).scalars():
            assert p.embedding == [1.0, 0.0]          # vector computed ONCE, at ingest
            assert p.requirements is not None         # extraction moved off the search path


def test_search_db_uses_stored_vectors_not_the_model(monkeypatch):
    # After ingest, scoring a profile must NOT embed the posting text again.
    _mock(monkeypatch)
    monkeypatch.setattr(crawl, "embed", lambda text: [1.0, 0.0])
    with SessionLocal() as db:
        crawl.ingest_from_sources(db)
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin, Compose")

        def no_posting_embeds(text):
            raise AssertionError("posting text must come from the stored vector")
        monkeypatch.setattr(crawl, "embed", lambda text: [1.0, 0.0])   # profile vector only
        monkeypatch.setattr(scoring, "embed", no_posting_embeds)
        res = crawl.search_db(db, p)
        assert res["scored"] == 1 and res["matched"] >= 1


def test_search_db_is_network_free(monkeypatch):
    # The whole point of Phase 1: Search now must never touch a source adapter.
    def boom(*a, **k):
        raise AssertionError("search_db must not fetch")
    monkeypatch.setattr(crawl, "fetch_all", boom)
    monkeypatch.setattr(crawl, "FAST_SOURCES", [("boom", boom)])
    monkeypatch.setattr(crawl, "PROFILE_SOURCES", [("boom", boom)])
    with SessionLocal() as db:
        db.add(Posting(title="Android Engineer", company="Acme", url="https://x/9",
                       description="Requirements:\n- Kotlin", content_hash="h9"))
        db.commit()
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin")
        res = crawl.search_db(db, p)
        assert res["pool"] == 1 and res["matched"] == 1


def test_urlless_postings_never_create_new_matches():
    # Staging grew demo rows without links ('Senior Android Engineer @ Acme', example.com) —
    # a match card with no Apply button is noise, so link-less postings are skipped unless the
    # profile ALREADY has a match (the owner pasted that JD via the manual form).
    with SessionLocal() as db:
        db.add(Posting(title="Android Engineer", company="Ghost", url="",
                       description="Requirements:\n- Kotlin experience", content_hash="ghost1"))
        db.commit()
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin")
        res = crawl.search_db(db, p)
        assert res["matched"] == 0
        assert db.execute(select(Match)).first() is None
        # but an existing match (manual paste flow) keeps refreshing
        post = db.execute(select(Posting)).scalars().one()
        db.add(Match(profile_id=p.id, posting_id=post.id, score=1)); db.commit()
        res = crawl.search_db(db, p)
        assert res["scored"] == 1
        assert db.execute(select(Match)).scalars().one().score > 1


def test_ingest_due_staleness():
    with SessionLocal() as db:
        assert ingest_due(db, 6)                              # never ran -> due
        db.add(CrawlRun(kind="ingest", ok=True, started_at=datetime.utcnow()))
        db.commit()
        assert not ingest_due(db, 6)                          # fresh -> not due
        db.add(CrawlRun(kind="ingest", ok=True,
                        started_at=datetime.utcnow() - timedelta(hours=7)))
        db.commit()
        assert not ingest_due(db, 6)                          # newest successful run counts
    with SessionLocal() as db:
        db.execute(CrawlRun.__table__.delete())
        db.add(CrawlRun(kind="ingest", ok=False, started_at=datetime.utcnow()))
        db.commit()
        assert ingest_due(db, 6)                              # failed runs don't reset the clock


def test_run_ingest_records_crawlrun(monkeypatch):
    _mock(monkeypatch)
    with SessionLocal() as db:
        res = run_ingest(db)
        assert res["added"] == 2
        run = db.execute(select(CrawlRun).where(CrawlRun.kind == "ingest")).scalars().one()
        assert run.ok and run.stats["totals"]["added"] == 2


def test_run_ingest_targets_active_profiles_only(monkeypatch):
    # Targeted (profile-aware) queries must run for active users' profiles and skip paused ones.
    _mock(monkeypatch, sample=[])
    seen = []
    monkeypatch.setattr(crawl, "PROFILE_SOURCES",
                        [("t", lambda profile: seen.append(profile.target_roles) or [])])
    from tests.test_jobs import _user
    with SessionLocal() as db:
        _user(db, "active@test.local")
        _user(db, "paused@test.local", found_job=True)
        run_ingest(db)
    assert seen == ["Android"]                                # only the active user's profile
