"""JobTiger sitemap adapter (HTTP mocked — hermetic). Crawl-delay is honoured via an injected
sleep so tests verify politeness without actually waiting."""
import app.data.sources.jobtiger as jt

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.jobtiger.bg/obiavi-za-rabota/dev-1</loc><lastmod>2026-07-20</lastmod></url>
<url><loc>https://www.jobtiger.bg/obiavi-za-rabota/known-2</loc><lastmod>2026-07-19</lastmod></url>
<url><loc>https://www.jobtiger.bg/obiavi-za-rabota/acc-3</loc><lastmod>2026-07-18</lastmod></url>
</urlset>"""

PAGE_LD = """<html><head>
<script type="application/ld+json">{"@graph":[
 {"@type":"Organization","name":"JobTiger"},
 {"@type":"JobPosting","title":"Счетоводител","datePosted":"2026-07-20",
  "hiringOrganization":{"@type":"Organization","name":"Acme Bulgaria"},
  "jobLocation":{"@type":"Place","address":{"addressLocality":"София","addressCountry":"BG"}},
  "description":"<p>Изисквания:</p><ul><li>Счетоводен опит 3+ години</li></ul>"}
]}</script></head><body></body></html>"""

PAGE_OG = """<html><head>
<meta property="og:title" content="IRC1 - Senior Technician - Обява за работа в JobTiger"/>
<meta property="og:description" content="Обява за работа - Фирма: Sensata; Местоположение: Пловдив; Бизнес сектор: електроника"/>
</head><body></body></html>"""


def _mock(monkeypatch, pages: dict):
    def fake_fetch(url, params=None, timeout=15.0):
        if url == jt.SITEMAP_URL:
            return SITEMAP
        return pages.get(url)
    monkeypatch.setattr(jt, "fetch_text", fake_fetch)


def test_sitemap_parsing(monkeypatch):
    _mock(monkeypatch, {})
    sm = jt.fetch_sitemap()
    assert len(sm) == 3
    assert sm[0] == ("https://www.jobtiger.bg/obiavi-za-rabota/dev-1", "2026-07-20")


def test_jsonld_parsing(monkeypatch):
    _mock(monkeypatch, {"https://www.jobtiger.bg/obiavi-za-rabota/dev-1": PAGE_LD})
    posts = jt.fetch(limit=1, delay=0)
    assert len(posts) == 1
    p = posts[0]
    assert p.title == "Счетоводител"                      # any profession, not just IT
    assert p.company == "Acme Bulgaria"
    assert p.location == "София, BG"
    assert "Счетоводен опит" in p.description and "<" not in p.description
    assert p.posted_at is not None


def test_og_fallback_when_no_jsonld(monkeypatch):
    _mock(monkeypatch, {"https://www.jobtiger.bg/obiavi-za-rabota/dev-1": PAGE_OG})
    p = jt.fetch(limit=1, delay=0)[0]
    assert p.title == "IRC1 - Senior Technician"
    assert p.company == "Sensata" and p.location == "Пловдив"


def test_skip_urls_spends_budget_on_new_only(monkeypatch):
    _mock(monkeypatch, {
        "https://www.jobtiger.bg/obiavi-za-rabota/dev-1": PAGE_LD,
        "https://www.jobtiger.bg/obiavi-za-rabota/acc-3": PAGE_LD,
    })
    fetched = []
    posts = jt.fetch(limit=5, delay=0,
                     skip_urls={"https://www.jobtiger.bg/obiavi-za-rabota/known-2"})
    assert len(posts) == 2                                # known-2 skipped before fetching


def test_crawl_delay_between_page_fetches(monkeypatch):
    _mock(monkeypatch, {
        "https://www.jobtiger.bg/obiavi-za-rabota/dev-1": PAGE_LD,
        "https://www.jobtiger.bg/obiavi-za-rabota/known-2": PAGE_LD,
        "https://www.jobtiger.bg/obiavi-za-rabota/acc-3": PAGE_LD,
    })
    naps = []
    jt.fetch(limit=3, delay=30, sleep=naps.append)
    assert naps == [30, 30]                               # N pages -> N-1 delays, none before 1st


def test_limit_respected(monkeypatch):
    _mock(monkeypatch, {u: PAGE_LD for u in [
        "https://www.jobtiger.bg/obiavi-za-rabota/dev-1",
        "https://www.jobtiger.bg/obiavi-za-rabota/known-2",
        "https://www.jobtiger.bg/obiavi-za-rabota/acc-3"]})
    assert len(jt.fetch(limit=2, delay=0)) == 2


def test_network_errors_tolerated(monkeypatch):
    monkeypatch.setattr(jt, "fetch_text", lambda url, params=None, timeout=15.0: None)
    assert jt.fetch_sitemap() == [] and jt.fetch(limit=3, delay=0) == []
