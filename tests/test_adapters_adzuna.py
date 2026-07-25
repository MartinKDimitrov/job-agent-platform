"""Adzuna — multi-country aggregator API adapter (search per country/term -> RawPostings)."""
import app.data.sources.adzuna as az


def _result(i, country):
    return {"id": i, "title": f"Engineer {i}", "redirect_url": f"https://adzuna/{country}/{i}",
            "company": {"display_name": "Acme"}, "location": {"display_name": "Berlin"},
            "created": "2026-07-20T10:00:00Z",
            "description": "A sufficiently long job description to pass the scoreable gate here."}


def _with_keys(monkeypatch):
    monkeypatch.setattr(az.settings, "adzuna_app_id", "id", raising=False)
    monkeypatch.setattr(az.settings, "adzuna_app_key", "key", raising=False)


def test_silent_noop_without_keys(monkeypatch):
    monkeypatch.setattr(az.settings, "adzuna_app_id", "", raising=False)
    monkeypatch.setattr(az.settings, "adzuna_app_key", "", raising=False)
    assert az.fetch(search_terms=["x"]) == []          # no keys -> no calls, no crash


def test_fetch_per_country_and_dedups(monkeypatch):
    _with_keys(monkeypatch)
    calls = []

    def fake(url, params=None, **k):
        calls.append((url, (params or {}).get("what")))
        country = url.split("/jobs/")[1].split("/")[0]
        return {"results": [_result(1, country), _result(1, country), _result(2, country)]}
    monkeypatch.setattr(az, "fetch_json", fake)
    posts = az.fetch(search_terms=["python"], countries=("de", "fr"), pages=1,
                     sleep=lambda *_: None)
    # 2 unique per country x 2 countries; ids namespaced by country so no cross-country collision
    assert len(posts) == 4
    assert {p.raw["country"] for p in posts} == {"DE", "FR"}
    assert all(c[1] == "python" for c in calls)        # the `what` term was passed
    p = next(p for p in posts if p.raw["country"] == "DE")
    assert p.company == "Acme" and p.location == "Berlin" and p.posted_at.year == 2026


def test_short_description_dropped(monkeypatch):
    _with_keys(monkeypatch)
    bad = {"id": 9, "title": "T", "redirect_url": "https://x/9",
           "company": {"display_name": "Y"}, "location": {"display_name": "Z"},
           "description": "too short"}
    monkeypatch.setattr(az, "fetch_json", lambda url, params=None, **k: {"results": [bad]})
    assert az.fetch(search_terms=["x"], countries=("de",), sleep=lambda *_: None) == []
