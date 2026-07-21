"""RemoteOK, WeWorkRemotely, Lever, Ashby adapters (HTTP mocked — hermetic)."""
import app.adapters.remoteok as rok
import app.adapters.wwr as wwr
import app.adapters.lever as lever
import app.adapters.ashby as ashby


# ---- RemoteOK ----
ROK = [
    {"legal": "notice", "last_updated": "x"},                       # element [0] is legal
    {"id": 7, "position": "Senior Android Engineer", "company": "Acme",
     "location": "Worldwide", "url": "https://remoteok.com/l/7",
     "apply_url": "https://remoteok.com/l/7/apply", "epoch": 1770000000,
     "description": "<p>Kotlin &amp; Compose</p>"},
    {"id": 8, "company": "NoTitle"},                                # no position -> skipped
]


def test_remoteok(monkeypatch):
    monkeypatch.setattr(rok, "fetch_json", lambda url, browser=False: ROK)
    posts = rok.fetch()
    assert len(posts) == 1
    p = posts[0]
    assert p.title == "Senior Android Engineer" and p.company == "Acme"
    assert p.source_kind == "rss" and p.location == "Worldwide"
    assert "Kotlin & Compose" in p.description and "<" not in p.description
    assert p.posted_at is not None


def test_remoteok_bad_shape(monkeypatch):
    monkeypatch.setattr(rok, "fetch_json", lambda url, browser=False: None)
    assert rok.fetch() == []


# ---- WeWorkRemotely ----
WWR_RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Sun Life: Clinical Consultant</title><region>Iowa</region>
 <link>https://weworkremotely.com/jobs/1</link>
 <description><![CDATA[<p>Great role &amp; team</p>]]></description>
 <pubDate>Tue, 21 Jul 2026 10:00:00 +0000</pubDate></item>
<item><title>No Colon Title Here</title><region></region>
 <link>https://weworkremotely.com/jobs/2</link><description>x</description></item>
</channel></rss>"""


def test_wwr(monkeypatch):
    monkeypatch.setattr(wwr, "fetch_text", lambda url, params=None, timeout=15.0: WWR_RSS)
    posts = wwr.fetch()
    assert len(posts) == 2
    assert posts[0].company == "Sun Life" and posts[0].title == "Clinical Consultant"
    assert posts[0].location == "Iowa" and posts[0].source_kind == "rss"
    assert "Great role & team" in posts[0].description
    assert posts[1].company == "" and posts[1].location == "Remote"   # no colon, no region


def test_wwr_error(monkeypatch):
    monkeypatch.setattr(wwr, "fetch_text", lambda url, params=None, timeout=15.0: None)
    assert wwr.fetch() == []


# ---- Lever ----
LEVER = [{
    "id": "abc", "text": "Backend Engineer",
    "categories": {"location": "Remote - EU"},
    "descriptionPlain": "Requirements: Kotlin, Ktor",
    "createdAt": 1770000000000,
    "hostedUrl": "https://jobs.lever.co/acme/abc",
    "applyUrl": "https://jobs.lever.co/acme/abc/apply",
}]


def test_lever(monkeypatch):
    monkeypatch.setattr(lever, "fetch_json", lambda url, params=None, browser=False: LEVER)
    p = lever.fetch("acme", "Acme Inc")[0]
    assert p.source_kind == "ats_api" and p.company == "Acme Inc"
    assert p.title == "Backend Engineer" and p.location == "Remote - EU"
    assert p.apply_url == "https://jobs.lever.co/acme/abc/apply"   # canonical (A5)
    assert "Kotlin" in p.description and p.posted_at is not None


def test_lever_error(monkeypatch):
    monkeypatch.setattr(lever, "fetch_json", lambda url, params=None, browser=False: None)
    assert lever.fetch("acme") == []


# ---- Ashby ----
ASHBY = {"jobs": [{
    "id": "9", "title": "Data Engineer", "location": "New York, NY (HQ)", "isRemote": True,
    "publishedAt": "2026-07-20T10:00:00Z",
    "jobUrl": "https://jobs.ashbyhq.com/acme/9",
    "applyUrl": "https://jobs.ashbyhq.com/acme/9/application",
    "descriptionPlain": "Build data pipelines with Python and SQL.",
}]}


def test_ashby(monkeypatch):
    monkeypatch.setattr(ashby, "fetch_json", lambda url, browser=False: ASHBY)
    p = ashby.fetch("acme", "Acme")[0]
    assert p.source_kind == "ats_api" and p.title == "Data Engineer"
    assert "Remote" in p.location                                   # isRemote annotated
    assert p.apply_url == "https://jobs.ashbyhq.com/acme/9/application"   # canonical (A5)
    assert "pipelines" in p.description and p.posted_at is not None


def test_ashby_error(monkeypatch):
    monkeypatch.setattr(ashby, "fetch_json", lambda url, browser=False: None)
    assert ashby.fetch("acme") == []
