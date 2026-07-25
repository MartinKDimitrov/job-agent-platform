"""karriere.nrw — NRW public-sector OpenData API adapter (paged JSON list -> RawPostings)."""
import app.data.sources.karriere_nrw as kn


def _feed(page):
    if page == 1:
        return {"count": 3, "pages": 2, "items": [
            {"uuid": "u1", "title": "Sachbearbeitung (m/w/d) im Bereich StVZO",
             "authority": "Bezirksregierung Köln", "location": "Köln", "published": "2026-07-08",
             "careerfield": [10], "workingtime": [2], "careergroup": 2, "benefit": [1, 4],
             "deadline": "2026-08-09"},
            {"uuid": "u1", "title": "Duplicate on same page", "authority": "X", "location": "Y"},
        ]}
    if page == 2:
        return {"count": 3, "pages": 2, "items": [
            {"uuid": "u2", "title": "IT-Systemadministration (m/w/d)",
             "authority": "Stadt Bochum", "location": "Bochum", "published": "bad-date",
             "careerfield": [3], "workingtime": [1]},
            {"uuid": "u3", "title": "", "authority": "Z"},           # no title -> dropped
        ]}
    return {"items": []}


def _fake_fetch_json(url, **kw):
    page = 2 if "page=2" in url else 1
    return _feed(page)


def test_fetch_pages_and_composes_postings(monkeypatch):
    monkeypatch.setattr(kn, "fetch_json", _fake_fetch_json)
    posts = kn.fetch(sleep=lambda *_: None)
    assert [p.external_id for p in posts] == ["u1", "u2"]      # deduped, empty-title dropped
    p = posts[0]
    assert p.company == "Bezirksregierung Köln" and p.location == "Köln"
    assert p.url == "https://karriere.nrw/stellenangebot/u1"
    assert p.apply_url == p.url and p.source_kind == "api"
    assert "Technische Verwaltung" in p.description        # careerfield code -> label
    assert "Home-Office" in p.description                  # benefit code -> label
    assert p.posted_at is not None and p.posted_at.year == 2026


def test_bad_date_and_missing_fields_are_safe(monkeypatch):
    monkeypatch.setattr(kn, "fetch_json", _fake_fetch_json)
    posts = kn.fetch(sleep=lambda *_: None)
    it = next(p for p in posts if p.external_id == "u2")
    assert it.posted_at is None                            # unparseable date -> None, no crash
    assert "IT und Telekommunikation" in it.description


def test_respects_max_pages(monkeypatch):
    seen_pages = []

    def rec(url, **kw):
        seen_pages.append(2 if "page=2" in url else 1)
        return _feed(2 if "page=2" in url else 1)
    monkeypatch.setattr(kn, "fetch_json", rec)
    kn.fetch(max_pages=1, sleep=lambda *_: None)
    assert seen_pages == [1]                               # never fetched page 2


def test_bad_top_level_response_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(kn, "fetch_json", lambda url, **kw: None)
    assert kn.fetch(sleep=lambda *_: None) == []
