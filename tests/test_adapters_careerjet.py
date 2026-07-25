"""Careerjet — global aggregator v4 API adapter (Basic-auth search per term/locale)."""
import base64

import app.data.sources.careerjet as cj


def _job(i, loc=None):
    return {"title": f"Engineer {i}", "url": f"https://careerjet/{i}", "company": "Acme",
            "locations": loc if loc is not None else ["Sofia, Bulgaria"],
            "date": "Wed, 15 Jul 2026 09:00:00 GMT", "salary": "3000 BGN",
            "salary_min": 3000, "salary_max": 4000, "salary_currency_code": "BGN",
            "site": "example.com",
            "description": "A sufficiently long job description to pass the scoreable gate here."}


def _with_key(monkeypatch):
    monkeypatch.setattr(cj.settings, "careerjet_api_key", "APIKEY", raising=False)
    monkeypatch.setattr(cj.settings, "careerjet_user_ip", "", raising=False)


def test_silent_noop_without_key(monkeypatch):
    monkeypatch.setattr(cj.settings, "careerjet_api_key", "", raising=False)
    assert cj.fetch(search_terms=["x"]) == []            # no key -> no calls, no crash


def test_fetch_basic_auth_locale_and_dedups(monkeypatch):
    _with_key(monkeypatch)
    calls = []

    def fake(url, params=None, headers=None, **k):
        calls.append((params, headers))
        return {"type": "JOBS", "hits": 2, "pages": 1, "jobs": [_job(1), _job(1), _job(2)]}
    monkeypatch.setattr(cj, "fetch_json", fake)
    posts = cj.fetch(search_terms=["python"], countries=("bg",), sleep=lambda *_: None)
    assert len(posts) == 2                               # url-namespaced id dedups job 1
    params, headers = calls[0]
    assert params["locale_code"] == "bg_BG" and params["keywords"] == "python"
    assert params["user_ip"] == "8.8.8.8"               # required-param default applied
    expected = "Basic " + base64.b64encode(b"APIKEY:").decode()
    assert headers["Authorization"] == expected         # API key as Basic-auth username
    p = posts[0]
    assert p.company == "Acme" and p.location == "Sofia, Bulgaria" and p.posted_at.year == 2026
    assert p.raw["salary_currency"] == "BGN" and p.raw["country"] == "BG"


def test_locations_string_and_short_desc(monkeypatch):
    _with_key(monkeypatch)
    ok = _job(5, loc="Berlin")                            # locations as a plain string
    bad = {"title": "T", "url": "https://x/9", "company": "Y", "description": "too short"}
    monkeypatch.setattr(cj, "fetch_json",
                        lambda url, params=None, headers=None, **k: {"jobs": [ok, bad]})
    posts = cj.fetch(search_terms=["x"], countries=("de",), sleep=lambda *_: None)
    assert len(posts) == 1 and posts[0].location == "Berlin"
