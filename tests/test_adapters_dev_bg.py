"""dev.bg RSS adapter (HTTP mocked — hermetic)."""
import app.data.sources.dev_bg as dv

FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Обява за Jobs</title>
<item>
  <title>Senior Android Developer</title>
  <link>https://dev.bg/company/jobads/acme-senior-android-developer/</link>
  <guid isPermaLink="false">https://dev.bg/company/jobads/senior-android-developer/</guid>
  <pubDate>Tue, 21 Jul 2026 15:55:29 +0000</pubDate>
  <description><![CDATA[Short teaser [...]]]></description>
  <content:encoded><![CDATA[<p>Изисквания:</p><ul><li>Kotlin &amp; Compose</li><li>5+ years</li></ul>]]></content:encoded>
</item>
<item>
  <title>QA Engineer</title>
  <link>https://dev.bg/company/jobads/beta-soft-qa-engineer/</link>
  <guid isPermaLink="false">https://dev.bg/company/jobads/qa-engineer/</guid>
  <pubDate>bad date</pubDate>
  <description><![CDATA[Manual testing role]]></description>
</item>
</channel></rss>"""


def _mock(monkeypatch, body=FEED):
    monkeypatch.setattr(dv, "fetch_text", lambda url, params=None, timeout=15.0: body)


def test_parses_items_with_full_content(monkeypatch):
    _mock(monkeypatch)
    posts = dv.fetch(categories=["mobile"])
    assert len(posts) == 2
    p = posts[0]
    assert p.title == "Senior Android Developer"
    assert p.url == p.apply_url == "https://dev.bg/company/jobads/acme-senior-android-developer/"
    assert p.source_kind == "rss"
    assert "Kotlin & Compose" in p.description and "<" not in p.description
    assert p.posted_at is not None


def test_company_heuristic_from_link_vs_guid(monkeypatch):
    _mock(monkeypatch)
    posts = dv.fetch(categories=["mobile"])
    assert posts[0].company == "Acme"
    assert posts[1].company == "Beta Soft"


def test_bad_pubdate_tolerated(monkeypatch):
    _mock(monkeypatch)
    assert dv.fetch(categories=["x"])[1].posted_at is None


def test_dedup_across_categories(monkeypatch):
    _mock(monkeypatch)                      # same feed returned for both categories
    posts = dv.fetch(categories=["mobile", "python"])
    assert len(posts) == 2                  # deduped by link


def test_network_error_and_bad_xml(monkeypatch):
    _mock(monkeypatch, body=None)
    assert dv.fetch(categories=["x"]) == []
    _mock(monkeypatch, body="not xml at all <<<")
    assert dv.fetch(categories=["x"]) == []
