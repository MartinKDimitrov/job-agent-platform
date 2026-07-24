"""softgarden adapter (DE mid-market ATS, schema.org JSON feed) + careers-page detection."""
import app.data.sources.softgarden as sg
import app.data.ats_detect as ad

FEED = {
    "@type": "DataFeed", "numberOfItems": 2,
    "dataFeedElement": [
        {"@type": "DataFeedItem", "item": {
            "@type": "JobPosting",
            "title": "Maschinen- und Anlagenführer (m/w/d)",
            "url": "https://acme.career.softgarden.de/jobs/61112757/maschinenfuehrer/",
            "identifier": {"name": "ACME Group", "@type": "PropertyValue", "value": 61112757},
            "jobLocation": {"address": {"@type": "PostalAddress", "addressLocality": "Regensburg"}},
            "description": "<b>Das ist Ihr Job</b>\n<ul><li>Bedienen von CNC-Zentren</li>"
                           "<li>Ueberwachen der Produktion und Qualitaetskontrolle</li></ul>",
        }},
        {"@type": "DataFeedItem", "item": {
            "@type": "JobPosting", "title": "Ferienjob",
            "url": "https://acme.career.softgarden.de/jobs/2/ferienjob/",
            "identifier": {"value": 2}, "description": "zu kurz",   # < 40 chars -> dropped
        }},
    ],
}


def test_fetch_parses_feed(monkeypatch):
    monkeypatch.setattr(sg, "fetch_json", lambda url, **k: FEED)
    posts = sg.fetch("https://acme.career.softgarden.de")
    assert len(posts) == 1                       # the too-short one is dropped
    p = posts[0]
    assert p.external_id == "61112757"
    assert p.title.startswith("Maschinen")
    assert p.company == "ACME Group"
    assert p.location == "Regensburg"
    assert "CNC" in p.description
    assert p.url.endswith("/maschinenfuehrer/")


def test_fetch_company_fallback(monkeypatch):
    feed = {"dataFeedElement": [{"item": {
        "title": "Engineer", "url": "https://x.career.softgarden.de/jobs/9/e/",
        "identifier": {"value": 9},
        "description": "A sufficiently long description to be scoreable by the pipeline here."}}]}
    monkeypatch.setattr(sg, "fetch_json", lambda url, **k: feed)
    posts = sg.fetch("https://x.career.softgarden.de", company_name="Fallback GmbH")
    assert posts[0].company == "Fallback GmbH"


def test_fetch_empty_or_bad_feed(monkeypatch):
    monkeypatch.setattr(sg, "fetch_json", lambda url, **k: None)
    assert sg.fetch("https://x.career.softgarden.de") == []
    monkeypatch.setattr(sg, "fetch_json", lambda url, **k: {"nope": 1})
    assert sg.fetch("https://x.career.softgarden.de") == []


def test_detection_from_careers_link(monkeypatch):
    careers = '<a href="https://beinbauer-group.career.softgarden.de/de/">Zu den Jobs</a>'
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: careers)
    assert ad.scan_careers_page("https://www.beinbauer.de/karriere") == (
        "softgarden", "https://beinbauer-group.career.softgarden.de")


def test_probe_checks_feed(monkeypatch):
    monkeypatch.setattr(ad, "fetch_json", lambda url, **k: {"dataFeedElement": []})
    assert ad._probe_softgarden("https://acme.career.softgarden.de")
    monkeypatch.setattr(ad, "fetch_json", lambda url, **k: {"error": 1})
    assert not ad._probe_softgarden("https://acme.career.softgarden.de")
