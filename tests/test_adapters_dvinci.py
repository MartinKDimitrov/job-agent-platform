"""d.vinci adapter (DE mid-market ATS: server-rendered list + JSON-LD detail) + detection."""
import app.data.sources.dvinci as dv
import app.data.ats_detect as ad

LIST = """<html><body>
  <a href="/de/jobs/20296/ausbildung-industriemechaniker">Ausbildung Industriemechaniker</a>
  <a href="/de/jobs/30631/schuelerpraktikum">Schülerpraktikum</a>
  <a href="/de/jobs/20296/ausbildung-industriemechaniker">dup id</a>
</body></html>"""

def _detail(title, city):
    return ('<html><head><script type="application/ld+json">'
            '{"@context":"https://schema.org/","@type":"JobPosting","title":"' + title + '",'
            '"datePosted":"2026-07-01","hiringOrganization":{"@type":"Organization","name":"Wanzl"},'
            '"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"'
            + city + '"}},"description":"<p>Sie montieren Baugruppen und pruefen die Qualitaet. '
            'Wartung und Instandhaltung technischer Systeme gehoeren dazu.</p>"}'
            '</script></head><body><h1>' + title + '</h1></body></html>')

PAGES = {
    "https://wanzl-karriere.dvinci-hr.com/de/jobs": LIST,
    "https://wanzl-karriere.dvinci-hr.com/de/jobs/20296/ausbildung-industriemechaniker":
        _detail("Ausbildung zum Industriemechaniker (m/w/d)", "Leipheim"),
    "https://wanzl-karriere.dvinci-hr.com/de/jobs/30631/schuelerpraktikum":
        _detail("Schülerpraktikum (m/w/d)", "Leipheim"),
}


def test_fetch_lists_then_parses_jsonld(monkeypatch):
    monkeypatch.setattr(dv, "fetch_text", lambda url, *a, **k: PAGES.get(url))
    posts = dv.fetch("https://wanzl-karriere.dvinci-hr.com", sleep=lambda *_: None)
    assert [p.external_id for p in posts] == ["20296", "30631"]     # deduped by id
    p = posts[0]
    assert p.title == "Ausbildung zum Industriemechaniker (m/w/d)"
    assert p.company == "Wanzl" and p.location == "Leipheim"
    assert "Baugruppen" in p.description and p.posted_at.year == 2026
    assert p.url.endswith("/20296/ausbildung-industriemechaniker")


def test_company_name_override(monkeypatch):
    monkeypatch.setattr(dv, "fetch_text", lambda url, *a, **k: PAGES.get(url))
    posts = dv.fetch("https://wanzl-karriere.dvinci-hr.com", company_name="Wanzl GmbH",
                     sleep=lambda *_: None)
    assert posts[0].company == "Wanzl GmbH"


def test_detection_from_careers_link(monkeypatch):
    careers = '<a href="https://wanzl-karriere.dvinci-hr.com/de/jobs/3/intro">Zu den Jobs</a>'
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: careers)
    assert ad.scan_careers_page("https://www.wanzl.com/de_DE/karriere") == (
        "dvinci", "https://wanzl-karriere.dvinci-hr.com")


def test_probe_checks_job_links(monkeypatch):
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: LIST)
    assert ad._probe_dvinci("https://wanzl-karriere.dvinci-hr.com")
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: "<html>no jobs</html>")
    assert not ad._probe_dvinci("https://wanzl-karriere.dvinci-hr.com")
