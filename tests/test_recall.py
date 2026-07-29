"""Hybrid recall (Phase 5): token OR vector OR shared-canonical-skill doors + guards."""
from sqlalchemy import select

import app.application.usecases.search as crawl
from app.application import vector_cache
from app.core.config import settings
from app.data.db import SessionLocal
from app.data.models import Posting, Match
from tests.test_crawl import _make_profile_row


def _post(db, title, chash, *, vec=None, skills=None, company="Acme"):
    reqs = [{"text": "Some requirement here", "kind": "must"}]
    if skills:
        reqs[0]["skills"] = skills
        reqs[0]["weight"] = 4
    p = Posting(title=title, company=company, url=f"https://x/{chash}",
                apply_url=f"https://x/{chash}", description="Requirements:\n- Some requirement",
                requirements=reqs, embedding=vec, content_hash=chash)
    db.add(p); db.commit(); db.refresh(p)
    return p


def test_vector_door_admits_title_mismatch(monkeypatch):
    # 'Platform Engineer' shares no title token with a 'Backend' profile — the stored
    # vector proximity lets it in anyway.
    monkeypatch.setattr(crawl, "embed_query", lambda text: [1.0, 0.0])
    with SessionLocal() as db:
        _post(db, "Platform Engineer", "v1", vec=[0.9, 0.1])
        p = _make_profile_row(db, target_roles="Backend", skills="Python")
        res = crawl.search_db(db, p)
        assert res["scored"] == 1


def test_vector_door_respects_threshold(monkeypatch):
    monkeypatch.setattr(crawl, "embed_query", lambda text: [1.0, 0.0])
    with SessionLocal() as db:
        _post(db, "Platform Engineer", "v2", vec=[0.1, 0.99])   # cos ~0.1 — far
        p = _make_profile_row(db, target_roles="Backend", skills="Python")
        res = crawl.search_db(db, p)
        assert res["scored"] == 0


def test_skill_door_admits_weak_title():
    with SessionLocal() as db:
        _post(db, "Software Engineer", "s1", skills=["kotlin"])
        p = _make_profile_row(db, target_roles="Backend", skills="Kotlin, Compose")
        res = crawl.search_db(db, p)
        assert res["scored"] == 1                     # shared canonical skill lets it in


def test_generic_skills_do_not_flood():
    with SessionLocal() as db:
        _post(db, "Accountant", "g1", skills=["git", "sql"])   # only generic overlap
        p = _make_profile_row(db, target_roles="Backend", skills="Python, Git, SQL")
        res = crawl.search_db(db, p)
        assert res["scored"] == 0


def test_candidate_cap_guard(monkeypatch):
    monkeypatch.setattr(settings, "recall_max_candidates", 5)
    monkeypatch.setattr(crawl, "embed_query", lambda text: [1.0, 0.0])
    with SessionLocal() as db:
        for i in range(10):                            # 10 vector-door-only candidates
            _post(db, f"Unrelated Title {i}", f"c{i}", vec=[1.0, 0.0])
        p = _make_profile_row(db, target_roles="Backend", skills="Python")
        res = crawl.search_db(db, p)
        assert res["scored"] <= 5


def test_cache_invalidation_on_ingest(monkeypatch):
    from tests.test_crawl import _mock
    _mock(monkeypatch)
    monkeypatch.setattr(crawl, "embed_passage", lambda text: [1.0, 0.0])
    monkeypatch.setattr(crawl, "embed_query", lambda text: [1.0, 0.0])
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin")
        assert crawl.search_db(db, p)["scored"] == 0   # cache loaded: empty index
        crawl.ingest_from_sources(db)                  # adds postings + invalidates cache
        res = crawl.search_db(db, p)
        assert res["scored"] >= 1                      # fresh cache sees the new rows
