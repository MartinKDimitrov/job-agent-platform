"""Company registry (ROADMAP 16б): ATS auto-detection, persistence, and ingest wiring."""
from sqlalchemy import select

import app.data.ats_detect as det
import app.application.usecases.search as crawl
from app.data.company_repo import boards_for, upsert_company
from app.data.db import SessionLocal
from app.data.models import Company, Posting
from app.domain.entities import RawPosting
from tests.test_crawl import _mock


# ---- slug guessing ----
def test_slug_guesses():
    assert det.slug_guesses("EGT Digital") == ["egtdigital", "egt-digital", "egt"]
    assert det.slug_guesses("Chaos") == ["chaos"]
    assert det.slug_guesses("A1") == []          # too short to probe safely
    assert det.slug_guesses("") == []


# ---- probing ----
def test_detect_by_probe(monkeypatch):
    def fake_json(url, params=None, timeout=15.0, browser=False):
        if "greenhouse" in url and "/egtdigital/" in url:
            return {"jobs": [{"id": 1}]}
        return None                                # everything else 404s
    monkeypatch.setattr(det, "fetch_json", fake_json)
    assert det.detect("EGT Digital") == ("greenhouse", "egtdigital")


def test_detect_none_when_no_board(monkeypatch):
    monkeypatch.setattr(det, "fetch_json", lambda *a, **k: None)
    monkeypatch.setattr(det, "fetch_text", lambda *a, **k: None)
    assert det.detect("Ghost Corp", careers_url="https://ghost.example/careers") is None


def test_detect_from_careers_page(monkeypatch):
    html = '<a href="https://jobs.lever.co/acme-corp?lever-source=site">Open roles</a>'
    monkeypatch.setattr(det, "fetch_text", lambda *a, **k: html)
    calls = []
    def fake_json(url, params=None, timeout=15.0, browser=False):
        calls.append(url)
        return [{"id": 1}] if "lever" in url and "acme-corp" in url else None
    monkeypatch.setattr(det, "fetch_json", fake_json)
    assert det.detect("Acme Corp", careers_url="https://acme.example/jobs") == ("lever", "acme-corp")
    assert any("acme-corp" in c for c in calls)   # the page's slug was verified live


def test_careers_page_dead_board_falls_back_to_probing(monkeypatch):
    html = '<script src="https://boards.greenhouse.io/deadslug/embed"></script>'
    monkeypatch.setattr(det, "fetch_text", lambda *a, **k: html)
    def fake_json(url, params=None, timeout=15.0, browser=False):
        return {"jobs": []} if "/acmecorp/" in url else None
    monkeypatch.setattr(det, "fetch_json", fake_json)
    assert det.detect("Acme Corp", careers_url="https://acme.example/jobs") == ("greenhouse", "acmecorp")


# ---- persistence ----
def test_upsert_and_boards_for():
    with SessionLocal() as db:
        upsert_company(db, "EGT Digital", ats="greenhouse", ats_slug="egtdigital")
        upsert_company(db, "Ghost Corp", active=False)              # probed, no ATS
        upsert_company(db, "EGT Digital", careers_url="https://egt.example")  # update, not dup
        assert boards_for(db, "greenhouse") == [("egtdigital", "EGT Digital")]
        assert boards_for(db, "lever") == []
        assert db.execute(select(Company)).scalars().all().__len__() == 2


# ---- ingest wiring ----
def test_ingest_crawls_registry_boards(monkeypatch):
    _mock(monkeypatch, sample=[])            # fast sources empty; registry supplies postings
    seen = []
    def fake_gh(slug, company_name=None):
        seen.append((slug, company_name))
        return [RawPosting("ats_api", "r1", "QA Engineer", company_name, location="Sofia",
                           url="https://egt.example/j/1", apply_url="https://egt.example/j/1",
                           description="Requirements:\n- Selenium experience")]
    monkeypatch.setattr(crawl.greenhouse, "fetch", fake_gh)
    with SessionLocal() as db:
        upsert_company(db, "EGT Digital", ats="greenhouse", ats_slug="egtdigital")
        upsert_company(db, "Inactive Co", ats="greenhouse", ats_slug="inactive", active=False)
        res = crawl.ingest_from_sources(db, boards=[])     # no seed boards — registry only
        assert seen == [("egtdigital", "EGT Digital")]     # active only
        assert res["added"] == 1
        assert db.execute(select(Posting)).scalars().one().company == "EGT Digital"
