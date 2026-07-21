"""Adapter framework + Greenhouse adapter (HTTP mocked, so hermetic and offline)."""
from sqlalchemy import select

import app.adapters.greenhouse as gh
from app.adapters.base import html_to_text, ingest, RawPosting, get_adapter
from app.db import SessionLocal
from app.models import Posting

SAMPLE = {"jobs": [
    {"id": 101, "title": "Senior Android Engineer",
     "absolute_url": "https://boards.greenhouse.io/acme/jobs/101",
     "location": {"name": "Remote - EU"},
     "content": "&lt;p&gt;Build &amp; ship apps.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Kotlin&lt;/li&gt;&lt;/ul&gt;",
     "updated_at": "2026-07-20T10:00:00Z"},
    {"id": 102, "title": "Backend Engineer",
     "absolute_url": "https://boards.greenhouse.io/acme/jobs/102",
     "location": {"name": "Sofia"}, "content": "", "updated_at": None},
]}


def _mock(monkeypatch, payload):
    monkeypatch.setattr(gh, "fetch_json", lambda url, params=None, timeout=15.0: payload)


def test_html_to_text_strips_tags_and_entities():
    assert html_to_text("&lt;p&gt;Hi&lt;br&gt;there&lt;/p&gt;").split("\n") == ["Hi", "there"]
    assert html_to_text("Build &amp; ship") == "Build & ship"
    assert html_to_text("") == ""


def test_fetch_normalizes(monkeypatch):
    _mock(monkeypatch, SAMPLE)
    posts = gh.fetch("acme", company_name="Acme Inc")
    assert len(posts) == 2
    p = posts[0]
    assert p.title == "Senior Android Engineer"
    assert p.url == p.apply_url == "https://boards.greenhouse.io/acme/jobs/101"
    assert p.company == "Acme Inc"
    assert p.location == "Remote - EU"
    assert p.external_id == "101"
    assert p.source_kind == "ats_api"
    assert "<" not in p.description and "Kotlin" in p.description   # HTML stripped to text
    assert p.posted_at is not None


def test_fetch_uses_token_as_company_when_no_name(monkeypatch):
    _mock(monkeypatch, SAMPLE)
    assert gh.fetch("acme")[0].company == "acme"


def test_fetch_handles_network_error_and_bad_shape(monkeypatch):
    _mock(monkeypatch, None)          # network/HTTP error -> None
    assert gh.fetch("acme") == []
    _mock(monkeypatch, {})            # unexpected shape (no "jobs")
    assert gh.fetch("acme") == []
    _mock(monkeypatch, {"jobs": []})  # empty board
    assert gh.fetch("acme") == []


def test_content_hash_is_stable_and_url_based():
    a = RawPosting("ats_api", "1", "T", "C", apply_url="https://x/apply/1")
    b = RawPosting("ats_api", "1", "T", "C", apply_url="https://x/apply/1")
    c = RawPosting("ats_api", "1", "T", "C", apply_url="https://x/apply/2")
    assert a.content_hash() == b.content_hash() != c.content_hash()


def test_adapter_is_registered():
    assert get_adapter("greenhouse") is gh.fetch


def test_ingest_upserts_without_duplicates(monkeypatch):
    _mock(monkeypatch, SAMPLE)
    posts = gh.fetch("acme")
    with SessionLocal() as db:
        r1 = ingest(db, posts)
        assert r1 == {"added": 2, "skipped": 0}
        r2 = ingest(db, posts)                       # same postings again
        assert r2 == {"added": 0, "skipped": 2}
        stored = db.execute(select(Posting)).scalars().all()
        assert len(stored) == 2
        row = db.execute(
            select(Posting).where(Posting.title == "Senior Android Engineer")).scalar_one()
        assert row.apply_url == "https://boards.greenhouse.io/acme/jobs/101"
