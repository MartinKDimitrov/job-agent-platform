"""Rabota.bg sitemap+JSON-LD adapter (HTTP mocked). Its sub-sitemaps mix static pages with job
ads (only /<cat>/<Y>/<M>/<D>/<slug>.<id> are ads); JSON-LD may embed raw newlines (strict=False)."""
import app.data.sources.rabota as rb

INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.rabota.bg/sitemaps/sitemap1.xml</loc></sitemap>
</sitemapindex>"""

SUB = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.rabota.bg/</loc></url>
<url><loc>https://www.rabota.bg/search.php</loc></url>
<url><loc>https://www.rabota.bg/proizvodstvo/2026/07/27/montajnik-sofia.400927</loc></url>
<url><loc>https://www.rabota.bg/tyrgoviia/2026/07/26/menidjyr-varna.400926</loc></url>
</urlset>"""

# NOTE the literal newline inside "description" — invalid to strict JSON, fine with strict=False
PAGE_LD = """<html><head>
<script type="application/ld+json">{"@context":"http://schema.org","@type":"JobPosting",
 "title":"Монтажник","datePosted":"2026-07-27",
 "hiringOrganization":{"@type":"Organization","name":"Алфа Консулт"},
 "jobLocation":{"@type":"Place","address":{"addressLocality":"София","addressCountry":"Bulgaria"}},
 "description":"Търсим монтажник\nс опит."}</script></head><body></body></html>"""


def _mock(monkeypatch, pages):
    def fake_fetch(url, params=None, timeout=15.0):
        if url == rb.SITEMAP_INDEX:
            return INDEX
        if url.endswith("sitemap1.xml"):
            return SUB
        return pages.get(url)
    monkeypatch.setattr(rb, "fetch_text", fake_fetch)


def test_sitemap_keeps_only_job_ads(monkeypatch):
    _mock(monkeypatch, {})
    sm = rb.fetch_sitemap()
    assert len(sm) == 2                                    # the two ad URLs, not / or /search.php
    assert all(u.rsplit(".", 1)[-1].isdigit() for u, _ in sm)


def test_jsonld_with_raw_newline_parses(monkeypatch):
    _mock(monkeypatch, {"https://www.rabota.bg/proizvodstvo/2026/07/27/montajnik-sofia.400927": PAGE_LD})
    posts = rb.fetch(limit=1, delay=0)
    assert len(posts) == 1
    p = posts[0]
    assert p.title == "Монтажник" and p.company == "Алфа Консулт"
    assert p.location == "София, Bulgaria"
    assert "монтажник" in p.description.lower() and p.posted_at is not None


def test_skip_urls_and_limit(monkeypatch):
    _mock(monkeypatch, {
        "https://www.rabota.bg/proizvodstvo/2026/07/27/montajnik-sofia.400927": PAGE_LD,
        "https://www.rabota.bg/tyrgoviia/2026/07/26/menidjyr-varna.400926": PAGE_LD})
    posts = rb.fetch(limit=5, delay=0,
                     skip_urls={"https://www.rabota.bg/tyrgoviia/2026/07/26/menidjyr-varna.400926"})
    assert len(posts) == 1


def test_network_errors_tolerated(monkeypatch):
    monkeypatch.setattr(rb, "fetch_text", lambda url, params=None, timeout=15.0: None)
    assert rb.fetch_sitemap() == [] and rb.fetch(limit=3, delay=0) == []
