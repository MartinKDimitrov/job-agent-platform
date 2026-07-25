"""Adzuna bulk pull — resumable category×country drain of all professions."""
import app.data.sources.adzuna as az
from app.application.usecases import adzuna_bulk as ab
from app.data.db import SessionLocal
from app.data.models import AdzunaPull


def _keys(monkeypatch):
    monkeypatch.setattr(az.settings, "adzuna_app_id", "id", raising=False)
    monkeypatch.setattr(az.settings, "adzuna_app_key", "key", raising=False)


def _page(country, page, n, total, category=None):
    """A search-response page with `n` valid results and a stated total count."""
    def one(i):
        return {"id": f"{page}-{i}", "title": f"Job {country} p{page} n{i}",
                "redirect_url": f"https://a/{country}/{page}/{i}",
                "company": {"display_name": f"Co {country} {page} {i}"},
                "location": {"display_name": "Berlin"},
                "created": "2026-07-20T10:00:00Z",
                "description": "A sufficiently long description to clear the scoreable gate here."}
    return {"count": total, "results": [one(i) for i in range(n)]}


# ---- fetch_page / categories -------------------------------------------------

def test_fetch_page_returns_posts_and_total(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(az, "fetch_json",
                        lambda url, params=None, **k: _page("de", 1, 3, 4321))
    posts, total = az.fetch_page("de", 1, category="it")
    assert total == 4321 and len(posts) == 3
    assert all(p.raw["country"] == "DE" for p in posts)


def test_fetch_page_noop_without_keys(monkeypatch):
    monkeypatch.setattr(az.settings, "adzuna_app_id", "", raising=False)
    monkeypatch.setattr(az.settings, "adzuna_app_key", "", raising=False)
    assert az.fetch_page("de", 1) == ([], 0)


def test_categories_maps_tag_label(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(az, "fetch_json", lambda url, params=None, **k: {
        "results": [{"tag": "it-jobs", "label": "IT Jobs"}, {"tag": "sales", "label": "Sales"}]})
    assert az.categories("de") == [("it-jobs", "IT Jobs"), ("sales", "Sales")]


# ---- ensure_slices -----------------------------------------------------------

def test_ensure_slices_seeds_one_row_per_country_category(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(ab.adzuna, "categories",
                        lambda c: [("it-jobs", "IT"), ("sales", "Sales")])
    created = ab.ensure_slices(SessionLocal, countries=("de", "fr"))
    assert created == 4                                    # 2 categories × 2 countries
    with SessionLocal() as db:
        assert db.query(AdzunaPull).count() == 4
    # idempotent: a second call creates nothing more
    assert ab.ensure_slices(SessionLocal, countries=("de", "fr")) == 0


# ---- run_bulk ----------------------------------------------------------------

def test_run_bulk_advances_cursor_and_persists(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(ab.adzuna, "categories", lambda c: [("it-jobs", "IT")])
    monkeypatch.setattr(ab, "RESULTS_PER_PAGE", 5)

    # slice has 2 full pages (5 each) then a short page (2) -> drained after 3 calls
    pages = {1: _page("de", 1, 5, 12), 2: _page("de", 2, 5, 12), 3: _page("de", 3, 2, 12)}

    def fake(country, page, *, category=None, what=None, results_per_page=5):
        j = pages[page]
        posts = [p for p in (az._to_posting(country, it) for it in j["results"]) if p]
        return posts, j["count"]
    monkeypatch.setattr(ab.adzuna, "fetch_page", fake)

    out = ab.run_bulk(SessionLocal, call_budget=10, results_per_page=5, countries=("de",),
                      sleep=lambda *_: None)
    assert out["configured"] and out["calls"] == 3 and out["added"] == 12
    with SessionLocal() as db:
        row = db.query(AdzunaPull).filter_by(country="de", category="it-jobs").one()
        assert row.done and row.pulled == 12 and row.total == 12 and row.next_page == 4


def test_run_bulk_resumes_from_cursor_and_respects_budget(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(ab.adzuna, "categories", lambda c: [("it-jobs", "IT")])

    def fake(country, page, *, category=None, what=None, results_per_page=5):
        j = _page(country, page, 5, 999)                  # always full -> never "done"
        posts = [p for p in (az._to_posting(country, it) for it in j["results"]) if p]
        return posts, 999
    monkeypatch.setattr(ab.adzuna, "fetch_page", fake)

    # budget 2 -> exactly 2 pages this run; cursor now at page 3, not done
    ab.run_bulk(SessionLocal, call_budget=2, pages_per_slice=10, results_per_page=5,
                countries=("de",), sleep=lambda *_: None)
    with SessionLocal() as db:
        row = db.query(AdzunaPull).filter_by(country="de").one()
        assert row.next_page == 3 and not row.done and row.pulled == 10

    # next run resumes at page 3
    ab.run_bulk(SessionLocal, call_budget=2, pages_per_slice=10, results_per_page=5,
                countries=("de",), sleep=lambda *_: None)
    with SessionLocal() as db:
        row = db.query(AdzunaPull).filter_by(country="de").one()
        assert row.next_page == 5 and row.pulled == 20


def test_run_bulk_noop_without_keys(monkeypatch):
    monkeypatch.setattr(az.settings, "adzuna_app_id", "", raising=False)
    monkeypatch.setattr(az.settings, "adzuna_app_key", "", raising=False)
    out = ab.run_bulk(SessionLocal, countries=("de",), sleep=lambda *_: None)
    assert out["configured"] is False and out["calls"] == 0


def test_status_reports_progress(monkeypatch):
    with SessionLocal() as db:
        db.add_all([
            AdzunaPull(country="de", category="it-jobs", label="IT", pulled=50, total=200, done=False),
            AdzunaPull(country="de", category="sales", label="Sales", pulled=30, total=30, done=True),
            AdzunaPull(country="fr", category="it-jobs", label="IT", pulled=20, total=100, done=False)])
        db.commit()
    with SessionLocal() as db:
        st = ab.status(db)
    assert st["slices"] == 3 and st["slices_done"] == 1
    assert st["pulled"] == 100 and st["est_total"] == 330
    assert st["pct"] == round(100 * 100 / 330, 1)
    assert st["by_country"]["DE"]["pulled"] == 80 and st["by_country"]["FR"]["pulled"] == 20


def test_render_board_reflects_status():
    st = {"slices": 2, "slices_done": 1, "pulled": 80, "est_total": 200, "pct": 40.0,
          "by_country": {"DE": {"pulled": 80, "total": 200, "slices": 2, "done": 1}},
          "slices_detail": [
              {"country": "DE", "category": "it-jobs", "label": "IT & Telecoms",
               "pulled": 50, "total": 200, "next_page": 2, "done": False, "updated_at": None},
              {"country": "DE", "category": "sales", "label": "Sales",
               "pulled": 30, "total": 30, "next_page": 2, "done": True, "updated_at": None}]}
    html = ab.render_board(st)
    assert "Adzuna Bulk Pull" in html and "40.0%" in html
    assert "IT &amp; Telecoms" in html          # label HTML-escaped
    assert "1</b> / <b>2</b> slices" in html
    assert "queued" not in html or "live" in html  # non-empty slice shows a live/done pill
