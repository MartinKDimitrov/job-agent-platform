"""Reed — UK Jobseeker API adapter (Basic-auth GET search -> RawPostings)."""
import base64

import app.data.sources.reed as rd


def _job(i):
    return {"jobId": i, "jobTitle": f"Engineer {i}", "jobUrl": f"https://reed/{i}",
            "employerName": "Acme", "locationName": "London", "date": "20/07/2026",
            "minimumSalary": 40000, "maximumSalary": 55000, "currency": "GBP",
            "expirationDate": "30/09/2026",
            "jobDescription": "A sufficiently long job description to pass the gate here."}


def _with_key(monkeypatch):
    monkeypatch.setattr(rd.settings, "reed_api_key", "k", raising=False)


def test_silent_noop_without_key(monkeypatch):
    monkeypatch.setattr(rd.settings, "reed_api_key", "", raising=False)
    assert rd.fetch(search_terms=["x"]) == []            # no key -> no calls, no crash


def test_fetch_basic_auth_params_and_dedup(monkeypatch):
    _with_key(monkeypatch)
    calls = []

    def fake(url, params=None, headers=None, **k):
        calls.append((url, params, headers))
        return {"totalResults": 3, "results": [_job(1), _job(1), _job(2)]}
    monkeypatch.setattr(rd, "fetch_json", fake)
    posts = rd.fetch(search_terms=["accountant"], sleep=lambda *_: None)
    assert len(posts) == 2                               # jobId 1 deduped within the batch
    url, params, headers = calls[0]
    assert url == "https://www.reed.co.uk/api/1.0/search"
    assert params["keywords"] == "accountant" and params["resultsToTake"] == 100
    token = base64.b64encode(b"k:").decode()             # key = Basic-auth username, empty pass
    assert headers["Authorization"] == f"Basic {token}"
    p = posts[0]
    assert p.external_id == "reed:1" and p.company == "Acme"
    assert p.location == "London, UK"                    # bare city gets the country appended
    assert p.posted_at.day == 20 and p.posted_at.month == 7   # dd/mm/yyyy, not mm/dd
    assert p.raw["salary_min"] == 40000 and p.raw["country"] == "GB"


def test_pagination_uses_skip_and_stops_on_empty(monkeypatch):
    _with_key(monkeypatch)
    calls = []

    def fake(url, params=None, headers=None, **k):
        calls.append(params["resultsToSkip"])
        return {"results": [_job(1)]} if params["resultsToSkip"] == 0 else {"results": []}
    monkeypatch.setattr(rd, "fetch_json", fake)
    posts = rd.fetch(search_terms=["x"], pages=3, sleep=lambda *_: None)
    assert len(posts) == 1
    assert calls == [0, 100]                             # empty page 2 stops the walk


def test_max_terms_caps_requests(monkeypatch):
    _with_key(monkeypatch)
    calls = []

    def fake(url, params=None, headers=None, **k):
        calls.append(params.get("keywords"))
        return {"results": [_job(1)]}
    monkeypatch.setattr(rd, "fetch_json", fake)
    rd.fetch(search_terms=["a", "b", "c"], max_terms=2, sleep=lambda *_: None)
    assert calls == ["a", "b"]


def test_short_description_dropped(monkeypatch):
    _with_key(monkeypatch)
    bad = {"jobId": 9, "jobTitle": "T", "jobUrl": "https://x/9", "employerName": "Y",
           "locationName": "Leeds", "jobDescription": "too short"}
    monkeypatch.setattr(rd, "fetch_json", lambda *a, **k: {"results": [bad]})
    assert rd.fetch(search_terms=["x"], sleep=lambda *_: None) == []
