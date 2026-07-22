"""Workable adapter (16в): v3 list + v2 detail, benefits excluded, pagination, degradation."""
import app.data.sources.workable as wk

LIST_PAGE = {
    "total": 2,
    "results": [
        {"shortcode": "AAA111", "title": "Senior AI Software Engineer", "remote": False,
         "location": {"city": "Sofia", "country": "Bulgaria"},
         "published": "2026-07-17T00:00:00.000Z"},
        {"shortcode": "BBB222", "title": "QA Engineer", "remote": True,
         "location": {"city": None, "country": "Bulgaria"}, "published": ""},
    ],
}

DETAIL = {
    "AAA111": {"description": "<p>We build insurance software.</p>",
               "requirements": ("<ul><li>Strong background in Java and Spring Boot</li></ul>"
                                "<p><strong>Nice to Have</strong></p>"
                                "<ul><li>Proficiency in Python</li></ul>"),
               "benefits": "<ul><li>Multisport card and food vouchers</li></ul>"},
    "BBB222": {"description": "", "requirements": "<ul><li>Selenium experience</li></ul>",
               "benefits": "<ul><li>25 days paid leave</li></ul>"},
}


def _mock(monkeypatch, pages=None):
    pages = pages if pages is not None else [LIST_PAGE]
    calls = {"n": 0}

    def fake_post(url, body, timeout=15.0):
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return page

    def fake_get(url, params=None, timeout=15.0, browser=False):
        code = url.rstrip("/").rsplit("/", 1)[-1]
        return DETAIL.get(code)

    monkeypatch.setattr(wk, "post_json", fake_post)
    monkeypatch.setattr(wk, "fetch_json", fake_get)
    return calls


def test_fetch_maps_fields(monkeypatch):
    _mock(monkeypatch)
    posts = wk.fetch("tinqin", company_name="TINQIN")
    assert len(posts) == 2
    p = posts[0]
    assert p.title == "Senior AI Software Engineer" and p.company == "TINQIN"
    assert p.location == "Sofia, Bulgaria"
    assert p.url == "https://apply.workable.com/tinqin/j/AAA111/"
    assert p.apply_url.endswith("/apply/")
    assert p.posted_at is not None
    assert posts[1].location == "Remote"                 # remote flag wins


def test_description_joins_reqs_and_skips_benefits(monkeypatch):
    _mock(monkeypatch)
    p = wk.fetch("tinqin")[0]
    assert "insurance software" in p.description
    assert "Requirements:" in p.description              # explicit header for the extractor
    assert "Java and Spring Boot" in p.description
    assert "Nice to Have" in p.description               # nice section flows through
    assert "Multisport" not in p.description             # benefits NEVER enter the text
    assert "vouchers" not in p.description


def test_pagination_token(monkeypatch):
    page1 = {"total": 2, "results": [LIST_PAGE["results"][0]], "nextPage": "tok1"}
    page2 = {"total": 2, "results": [LIST_PAGE["results"][1]]}
    calls = _mock(monkeypatch, pages=[page1, page2])
    posts = wk.fetch("tinqin")
    assert [p.external_id for p in posts] == ["AAA111", "BBB222"]
    assert calls["n"] == 2


def test_max_jobs_cap(monkeypatch):
    page = {"total": 2, "results": LIST_PAGE["results"], "nextPage": "tok"}
    _mock(monkeypatch, pages=[page])
    assert len(wk.fetch("tinqin", max_jobs=1)) == 1


def test_dead_account_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(wk, "post_json", lambda url, body, timeout=15.0: None)
    assert wk.fetch("ghost") == []
    monkeypatch.setattr(wk, "post_json",
                        lambda url, body, timeout=15.0: {"total": 0, "results": []})
    assert wk.fetch("dormant") == []                     # exists but publishes nothing
