"""Aggregator fallback — Careerjet + Jooble sweep when Adzuna is rate-limited."""
from app.application.usecases import aggregator_fallback as af
from app.data.db import SessionLocal
from app.data.models import Posting
from app.domain.entities import RawPosting
from sqlalchemy import func, select


def _posts(src, term, n):
    return [RawPosting("api", f"https://{src}/{term}/{i}", f"{term} role {i}", f"Co {src} {i}",
                       url=f"https://{src}/{term}/{i}", apply_url=f"https://{src}/{term}/{i}",
                       description="A sufficiently long job description to clear the gate here.")
            for i in range(n)]


def test_fallback_sweeps_both_and_caps_jooble(monkeypatch):
    cj_terms, jb_terms = [], []
    monkeypatch.setattr(af.careerjet, "fetch",
                        lambda search_terms=None, **k: (cj_terms.append(search_terms[0])
                                                        or _posts("cj", search_terms[0], 2)))
    monkeypatch.setattr(af.jooble, "fetch",
                        lambda search_terms=None, **k: (jb_terms.append(search_terms[0])
                                                        or _posts("jb", search_terms[0], 3)))
    out = af.run_aggregator_fallback(SessionLocal, terms=["a", "b", "c", "d", "e"],
                                     careerjet_terms=4, jooble_terms=2, sleep=lambda *_: None)
    assert cj_terms == ["a", "b", "c", "d"]           # careerjet capped at 4 terms
    assert jb_terms == ["a", "b"]                      # jooble capped hard at 2 (500-cap guard)
    assert out["careerjet_added"] == 8 and out["jooble_added"] == 6
    assert out["total_added"] == 14
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Posting.id))) == 14


def test_fallback_noop_when_sources_unconfigured(monkeypatch):
    # both adapters silently return [] without keys -> nothing added, no crash
    monkeypatch.setattr(af.careerjet, "fetch", lambda search_terms=None, **k: [])
    monkeypatch.setattr(af.jooble, "fetch", lambda search_terms=None, **k: [])
    out = af.run_aggregator_fallback(SessionLocal, terms=["a", "b"], sleep=lambda *_: None)
    assert out["total_added"] == 0
