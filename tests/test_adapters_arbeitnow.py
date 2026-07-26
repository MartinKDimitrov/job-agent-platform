"""Arbeitnow — free DE/EU aggregator API adapter (paged JSON -> RawPostings)."""
import app.data.sources.arbeitnow as an


def _feed(page):
    if page == 1:
        return {"data": [
            {"slug": "a1", "title": "Backend Engineer (m/w/d)", "company_name": "Acme GmbH",
             "location": "Berlin", "url": "https://www.arbeitnow.com/jobs/a1", "remote": True,
             "description": "<p>Sie bauen Services und APIs. Erfahrung mit Python und SQL noetig.</p>",
             "created_at": 1784000000},
            {"slug": "a1", "title": "dup", "url": "x", "description": "y"},          # dup slug
            {"slug": "short", "title": "T", "url": "https://x/y", "description": "too short"},
        ], "meta": {"current_page": 1}}
    if page == 2:
        return {"data": [
            {"slug": "b2", "title": "Data Analyst", "company_name": "Beta AG", "location": "Munich",
             "url": "https://www.arbeitnow.com/jobs/b2", "created_at": "2026-07-20T00:00:00Z",
             "description": "Analyse von Daten, Reporting und Dashboards fuer die Fachbereiche."}
        ], "meta": {"current_page": 2}}
    return {"data": [], "meta": {}}                                                 # empty -> stop


def test_fetch_pages_until_empty(monkeypatch):
    monkeypatch.setattr(an, "fetch_json",
                        lambda url, **k: _feed(2 if "page=2" in url else (3 if "page=3" in url else 1)))
    posts = an.fetch(max_pages=5, sleep=lambda *_: None)
    assert [p.external_id for p in posts] == ["a1", "b2"]         # deduped, short dropped, stops at empty
    p = posts[0]
    assert p.title == "Backend Engineer (m/w/d)" and p.company == "Acme GmbH"
    assert p.location == "Berlin" and p.url.endswith("/a1")
    assert "APIs" in p.description and p.posted_at.year == 2026   # unix ts parsed


def test_iso_date_and_max_pages(monkeypatch):
    calls = []

    def rec(url, **k):
        calls.append(url)
        return _feed(2 if "page=2" in url else 1)
    monkeypatch.setattr(an, "fetch_json", rec)
    posts = an.fetch(max_pages=1, sleep=lambda *_: None)
    assert len(calls) == 1                                        # respected max_pages=1
    assert posts[0].posted_at is not None


def test_bad_response_stops(monkeypatch):
    monkeypatch.setattr(an, "fetch_json", lambda url, **k: None)
    assert an.fetch(sleep=lambda *_: None) == []
