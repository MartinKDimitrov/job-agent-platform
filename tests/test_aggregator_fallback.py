"""Aggregator fallback — Careerjet + Jooble sweep when Adzuna is rate-limited."""
from app.application.usecases import aggregator_fallback as af
from app.data.db import SessionLocal
from app.data.models import Posting, AggregatorPull
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
        # per-(source, term) tallies recorded for the boards
        assert db.scalar(select(func.count(AggregatorPull.id))) == 6   # 4 careerjet + 2 jooble
        st = af.status(db, "careerjet")
        assert st["terms"] == 4 and st["pulled"] == 8
        assert af.status(db, "jooble")["pulled"] == 6


def test_render_board_reflects_status():
    st = {"source": "careerjet", "terms": 2, "pulled": 30, "seen": 40, "last_run": None,
          "rows": [{"term": "nurse", "pulled": 20, "seen": 25, "runs": 2, "updated_at": None},
                   {"term": "driver", "pulled": 10, "seen": 15, "runs": 1, "updated_at": None}]}
    html = af.render_board("careerjet", st)
    assert "Careerjet" in html and "nurse" in html and "driver" in html
    assert "30<small>" in html                     # unique-collected hero number


def test_fallback_passes_pagination_depth(monkeypatch):
    """Deeper pages surface many more of the same profession — the fallback must forward the
    page count to each adapter (Jooble kept shallower to protect its 500-request cap)."""
    seen = {}

    def cjfetch(search_terms=None, pages=1, **k):
        seen["cj"] = pages
        return _posts("cj", search_terms[0], 2)

    def jbfetch(search_terms=None, pages=1, **k):
        seen["jb"] = pages
        return _posts("jb", search_terms[0], 2)
    monkeypatch.setattr(af.careerjet, "fetch", cjfetch)
    monkeypatch.setattr(af.jooble, "fetch", jbfetch)
    af.run_aggregator_fallback(SessionLocal, terms=["nurse"], careerjet_terms=1, jooble_terms=1,
                               careerjet_pages=4, jooble_pages=2, sleep=lambda *_: None)
    assert seen["cj"] == 4 and seen["jb"] == 2


def test_fallback_noop_when_sources_unconfigured(monkeypatch):
    # both adapters silently return [] without keys -> nothing added, no crash
    monkeypatch.setattr(af.careerjet, "fetch", lambda search_terms=None, **k: [])
    monkeypatch.setattr(af.jooble, "fetch", lambda search_terms=None, **k: [])
    out = af.run_aggregator_fallback(SessionLocal, terms=["a", "b"], sleep=lambda *_: None)
    assert out["total_added"] == 0
