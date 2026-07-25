"""Jooble — pan-European aggregator API adapter (POST search per term -> RawPostings)."""
import app.data.sources.jooble as jb


def _job(i):
    return {"id": i, "title": f"Engineer {i}", "link": f"https://jooble/{i}",
            "company": "Acme", "location": "Sofia", "updated": "2026-07-20T10:00:00.000Z",
            "salary": "3000 BGN", "type": "Full-time", "source": "example.com",
            "snippet": "A sufficiently long job description to pass the scoreable gate here."}


def _with_key(monkeypatch):
    monkeypatch.setattr(jb.settings, "jooble_api_key", "k", raising=False)


def test_silent_noop_without_key(monkeypatch):
    monkeypatch.setattr(jb.settings, "jooble_api_key", "", raising=False)
    assert jb.fetch(search_terms=["x"]) == []           # no key -> no calls, no crash


def test_fetch_posts_key_in_url_and_dedups(monkeypatch):
    _with_key(monkeypatch)
    calls = []

    def fake(url, body, **k):
        calls.append((url, body.get("keywords")))
        return {"totalCount": 3, "jobs": [_job(1), _job(1), _job(2)]}
    monkeypatch.setattr(jb, "post_json", fake)
    posts = jb.fetch(search_terms=["python"], sleep=lambda *_: None)
    assert len(posts) == 2                               # id 1 deduped within the batch
    assert calls[0][0].endswith("/api/k")                # key travels in the URL path
    assert calls[0][1] == "python"                       # keyword posted in the body
    p = posts[0]
    assert p.company == "Acme" and p.location == "Sofia" and p.posted_at.year == 2026
    assert p.external_id == "jooble:1" and p.apply_url == "https://jooble/1"


def test_short_snippet_dropped(monkeypatch):
    _with_key(monkeypatch)
    bad = {"id": 9, "title": "T", "link": "https://x/9", "company": "Y", "location": "Z",
           "snippet": "too short"}
    monkeypatch.setattr(jb, "post_json", lambda url, body, **k: {"jobs": [bad]})
    assert jb.fetch(search_terms=["x"], sleep=lambda *_: None) == []
