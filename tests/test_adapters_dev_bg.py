"""dev.bg RSS adapter: global paged feed + targeted search feed (HTTP mocked — hermetic)."""
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

SEARCH_FEED = FEED.replace("acme-senior-android-developer", "novarto-mid-senior-android-engineer") \
                  .replace("senior-android-developer/</guid>", "mid-senior-android-engineer/</guid>") \
                  .replace("<title>Senior Android Developer</title>",
                           "<title>Mid/Senior Android Engineer</title>")

EMPTY = '<?xml version="1.0"?><rss><channel><title>x</title></channel></rss>'


class Recorder:
    """fetch_text stand-in that records requested params and serves canned pages."""
    def __init__(self, pages: dict):
        self.pages = pages          # key: (kind, page) where kind is 'global' or the term
        self.calls = []

    def __call__(self, url, params=None, timeout=15.0):
        params = params or {}
        page = int(params.get("paged", 1))
        kind = params["s"] if "s" in params else "global"
        self.calls.append((kind, page))
        return self.pages.get((kind, page), EMPTY)


def test_global_feed_paginates(monkeypatch):
    rec = Recorder({("global", 1): FEED, ("global", 2): FEED.replace("acme-", "globex-")})
    monkeypatch.setattr(dv, "fetch_text", rec)
    posts = dv.fetch(pages=3)
    assert ("global", 1) in rec.calls and ("global", 2) in rec.calls
    assert ("global", 3) in rec.calls                 # tried page 3, got empty -> stopped
    assert len(posts) == 3                            # 2 unique from p1 + 1 new from p2 (dedup)


def test_targeted_search_uses_search_feed(monkeypatch):
    rec = Recorder({("global", 1): FEED, ("android developer", 1): SEARCH_FEED})
    monkeypatch.setattr(dv, "fetch_text", rec)
    posts = dv.fetch(search_terms=["android developer"], pages=1, search_pages=1)
    kinds = {k for k, _ in rec.calls}
    assert kinds == {"global", "android developer"}
    titles = {p.title for p in posts}
    assert "Mid/Senior Android Engineer" in titles    # reached via the search feed
    assert any(p.company == "Novarto" for p in posts) # company from the link slug


def test_search_only_mode_skips_global(monkeypatch):
    rec = Recorder({("android", 1): SEARCH_FEED})
    monkeypatch.setattr(dv, "fetch_text", rec)
    posts = dv.fetch(search_terms=["android"], pages=0, search_pages=1)
    assert all(k != "global" for k, _ in rec.calls)   # pages=0 -> no global feed requests
    assert len(posts) == 2


def test_dedup_across_feeds(monkeypatch):
    rec = Recorder({("global", 1): FEED, ("qa", 1): FEED})   # same items in both feeds
    monkeypatch.setattr(dv, "fetch_text", rec)
    posts = dv.fetch(search_terms=["qa"], pages=1, search_pages=1)
    assert len(posts) == 2                            # deduped by link


def test_company_heuristic_and_content(monkeypatch):
    rec = Recorder({("global", 1): FEED})
    monkeypatch.setattr(dv, "fetch_text", rec)
    posts = dv.fetch(pages=1)
    assert posts[0].company == "Acme"
    assert posts[1].company == "Beta Soft"
    assert "Kotlin & Compose" in posts[0].description and "<" not in posts[0].description
    assert posts[0].posted_at is not None and posts[1].posted_at is None


def test_network_error_and_bad_xml(monkeypatch):
    monkeypatch.setattr(dv, "fetch_text", lambda url, params=None, timeout=15.0: None)
    assert dv.fetch(pages=2) == []
    monkeypatch.setattr(dv, "fetch_text", lambda url, params=None, timeout=15.0: "not xml <<<")
    assert dv.fetch(pages=2) == []