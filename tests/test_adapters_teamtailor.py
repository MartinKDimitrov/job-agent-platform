"""Teamtailor adapter (16в): jobs.rss parsing, custom-domain base URLs, remote mapping."""
import app.data.sources.teamtailor as tt

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel><title>myPOS</title>
    <item>
      <title>Senior Android Developer</title>
      <description>&lt;p&gt;Build our payments app.&lt;/p&gt;&lt;p&gt;Requirements:&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Kotlin experience&lt;/li&gt;&lt;/ul&gt;</description>
      <pubDate>Wed, 22 Jul 2026 12:52:44 +0300</pubDate>
      <link>https://careers.mypos.com/jobs/810-senior-android-developer</link>
      <remoteStatus>hybrid</remoteStatus>
      <guid>b7a9952e-1111</guid>
      <company_name>myPOS</company_name>
      <tt:locations><tt:location><tt:name>Sofia</tt:name><tt:city>Sofia</tt:city>
      <tt:country>Bulgaria</tt:country></tt:location></tt:locations>
      <tt:department>Engineering</tt:department>
    </item>
    <item>
      <title>Support Agent</title>
      <description>Help customers.</description>
      <link>https://careers.mypos.com/jobs/811-support-agent</link>
      <remoteStatus>fully</remoteStatus>
      <guid>b7a9952e-2222</guid>
    </item>
  </channel>
</rss>"""


def test_base_url_accepts_slug_and_url():
    assert tt.base_url("acme") == "https://acme.teamtailor.com"
    assert tt.base_url("https://careers.mypos.com/") == "https://careers.mypos.com"


def test_fetch_parses_items(monkeypatch):
    urls = []
    monkeypatch.setattr(tt, "fetch_text", lambda url, params=None, timeout=15.0:
                        urls.append(url) or RSS)
    posts = tt.fetch("https://careers.mypos.com", company_name="myPOS")
    assert urls == ["https://careers.mypos.com/jobs.rss"]
    assert len(posts) == 2
    p = posts[0]
    assert p.title == "Senior Android Developer" and p.company == "myPOS"
    assert p.location == "Sofia, Bulgaria (hybrid)"
    assert p.url == "https://careers.mypos.com/jobs/810-senior-android-developer"
    assert "Kotlin experience" in p.description and "<" not in p.description
    assert p.posted_at is not None
    assert posts[1].location == "Remote"              # remoteStatus=fully
    assert posts[1].company == "myPOS"


def test_company_from_feed_when_not_given(monkeypatch):
    monkeypatch.setattr(tt, "fetch_text", lambda *a, **k: RSS)
    assert tt.fetch("mypos")[0].company == "myPOS"    # company_name tag from the feed


def test_dead_site_degrades(monkeypatch):
    monkeypatch.setattr(tt, "fetch_text", lambda *a, **k: None)
    assert tt.fetch("ghost") == []
    monkeypatch.setattr(tt, "fetch_text", lambda *a, **k: "not xml <<<")
    assert tt.fetch("ghost") == []
