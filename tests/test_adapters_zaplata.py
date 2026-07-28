"""Zaplata.bg sitemap+JSON-LD adapter (HTTP mocked — hermetic). Unlike JobTiger it has no
crawl-delay, and its sitemap is an INDEX that must be resolved to the ad sub-sitemaps first."""
import app.data.sources.zaplata as zp

INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.zaplata.bg/sitemaps/sitemap-ads-1.xml</loc></sitemap>
<sitemap><loc>https://www.zaplata.bg/sitemaps/sitemap-companies-1.xml</loc></sitemap>
</sitemapindex>"""

ADS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.zaplata.bg/proizvodstvo/varna/1/montazhnik/</loc><lastmod>2026-07-27</lastmod></url>
<url><loc>https://www.zaplata.bg/shofiori/sofia/2/shofior/</loc><lastmod>2026-07-26</lastmod></url>
</urlset>"""

PAGE_LD = """<html><head>
<script type="application/ld+json">{"@type":"JobPosting","title":"Монтажник","datePosted":"2026-07-27",
 "hiringOrganization":{"@type":"Organization","name":"Про-Стил Варна ЕООД"},
 "jobLocation":{"@type":"Place","address":{"addressLocality":"Варна","addressCountry":"BG"}},
 "description":"<p>Търсим монтажник с опит.</p>"}</script></head><body></body></html>"""

PAGE_OG = """<html><head>
<meta property="og:title" content="Шофьор с категория С 2 - обява за работа в Zaplata.bg"/>
<meta property="og:description" content="Търсим шофьор."/>
</head><body></body></html>"""


def _mock(monkeypatch, pages):
    def fake_fetch(url, params=None, timeout=15.0):
        if url == zp.SITEMAP_INDEX:
            return INDEX
        if url.endswith("sitemap-ads-1.xml"):
            return ADS
        return pages.get(url)
    monkeypatch.setattr(zp, "fetch_text", fake_fetch)


def test_sitemap_index_resolves_to_ad_urls(monkeypatch):
    _mock(monkeypatch, {})
    sm = zp.fetch_sitemap()
    assert len(sm) == 2                                   # only the ad sub-sitemap, not companies
    assert sm[0][0] == "https://www.zaplata.bg/proizvodstvo/varna/1/montazhnik/"


def test_jsonld_parsing(monkeypatch):
    _mock(monkeypatch, {"https://www.zaplata.bg/proizvodstvo/varna/1/montazhnik/": PAGE_LD})
    posts = zp.fetch(limit=1, delay=0)
    assert len(posts) == 1
    p = posts[0]
    assert p.title == "Монтажник" and p.company == "Про-Стил Варна ЕООД"
    assert p.location == "Варна, BG"
    assert "монтажник" in p.description.lower() and "<" not in p.description
    assert p.posted_at is not None


def test_og_fallback_strips_zaplata_tail(monkeypatch):
    _mock(monkeypatch, {"https://www.zaplata.bg/proizvodstvo/varna/1/montazhnik/": PAGE_OG})
    p = zp.fetch(limit=1, delay=0)[0]
    assert p.title == "Шофьор с категория С 2"            # site tail removed


def test_skip_urls_and_limit(monkeypatch):
    _mock(monkeypatch, {
        "https://www.zaplata.bg/proizvodstvo/varna/1/montazhnik/": PAGE_LD,
        "https://www.zaplata.bg/shofiori/sofia/2/shofior/": PAGE_LD})
    posts = zp.fetch(limit=5, delay=0,
                     skip_urls={"https://www.zaplata.bg/shofiori/sofia/2/shofior/"})
    assert len(posts) == 1                                # the known URL is skipped before fetch


def test_no_crawl_delay_default_is_gentle(monkeypatch):
    _mock(monkeypatch, {
        "https://www.zaplata.bg/proizvodstvo/varna/1/montazhnik/": PAGE_LD,
        "https://www.zaplata.bg/shofiori/sofia/2/shofior/": PAGE_LD})
    naps = []
    zp.fetch(limit=2, delay=0.5, sleep=naps.append)
    assert naps == [0.5] and zp.CRAWL_DELAY < 5           # N pages -> N-1 delays; fast, not 30s


def test_network_errors_tolerated(monkeypatch):
    monkeypatch.setattr(zp, "fetch_text", lambda url, params=None, timeout=15.0: None)
    assert zp.fetch_sitemap() == [] and zp.fetch(limit=3, delay=0) == []
