"""rexx systems adapter (German mid-market ATS) + its careers-page detection."""
import app.data.sources.rexx as rx
import app.data.ats_detect as ad

LIST_HTML = """
<html><body><div class="joblist">
  <a href="https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html?yid=101" target="_top">Elektroniker (m/w/d)</a>
  <a href="https://career.acme.de/en/job-openings/current-job-offers.html?yid=102" target="_top">Quality Engineer (m/f/d)</a>
  <a href="https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html?yid=101" target="_top">Elektroniker (m/w/d)</a>
  <a href="https://www.rexx-systems.com">powered by rexx</a>
</div></body></html>
"""

DETAIL_101 = """
<html><head><title>Stellenangebot Elektroniker (m/w/d) bei ACME GmbH</title>
<meta name="description" content="Vollzeit in Musterstadt (Germany)" /></head>
<body><div id="main_content"><h1>Elektroniker (m/w/d)</h1>
<div class="scheme-task"><p>Sie montieren Baugruppen und nehmen Geraete in Betrieb.
Wartung und Instandhaltung technischer Systeme gehoeren zu Ihren Aufgaben.</p></div>
</div><div class="rexx_footer">Impressum</div></body></html>
"""

DETAIL_102 = """
<html><head><title>Job Quality Engineer (m/f/d) bei ACME GmbH</title>
<meta name="description" content="Full time in Musterstadt (Germany)" /></head>
<body><div id="main_content"><h1>Quality Engineer (m/f/d)</h1>
<div class="scheme-task"><p>You ensure product quality across the production line and
run audits, drive corrective actions and support suppliers.</p></div>
</div><div class="rexx_footer">Impressum</div></body></html>
"""

PAGES = {
    "https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html": LIST_HTML,
    "https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html?yid=101": DETAIL_101,
    "https://career.acme.de/en/job-openings/current-job-offers.html?yid=102": DETAIL_102,
}


def test_fetch_parses_postings(monkeypatch):
    monkeypatch.setattr(rx, "fetch_text", lambda url, *a, **k: PAGES.get(url))
    posts = rx.fetch("https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html",
                     company_name="ACME GmbH", sleep=lambda *_: None)
    assert [p.external_id for p in posts] == ["101", "102"]   # deduped by yid, order kept
    p = posts[0]
    assert p.title == "Elektroniker (m/w/d)"
    assert p.company == "ACME GmbH"
    assert p.location == "Musterstadt"
    assert "Baugruppen" in p.description
    assert p.url.endswith("yid=101")


def test_fetch_reads_company_from_title_when_unset(monkeypatch):
    monkeypatch.setattr(rx, "fetch_text", lambda url, *a, **k: PAGES.get(url))
    posts = rx.fetch("https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html",
                     sleep=lambda *_: None)
    assert posts[0].company == "ACME GmbH"


def test_detection_from_tenant_portal_link(monkeypatch):
    careers = ('<a href="https://preh8-portal.rexx-recruitment.com/stellenangebote.html">'
               'Stellen</a>')
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: careers)
    assert ad.scan_careers_page("https://www.preh.com/karriere") == (
        "rexx", "https://preh8-portal.rexx-recruitment.com/stellenangebote.html")


def test_detection_from_company_mirror_link(monkeypatch):
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: LIST_HTML)
    ats, slug = ad.scan_careers_page("https://www.acme.de/karriere")
    assert ats == "rexx"
    assert slug == "https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html"


def test_vendor_site_link_is_not_a_board(monkeypatch):
    # a page that only brand-links rexx-SYSTEMS.com (the vendor) must NOT detect as a board
    monkeypatch.setattr(ad, "fetch_text",
                        lambda url, *a, **k: '<a href="https://www.rexx-systems.com">rexx</a>')
    assert ad.scan_careers_page("https://www.acme.de/karriere") is None


def test_probe_requires_live_yid(monkeypatch):
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: LIST_HTML)
    assert ad._probe_rexx("https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html")
    monkeypatch.setattr(ad, "fetch_text", lambda url, *a, **k: "<html>no jobs</html>")
    assert not ad._probe_rexx("https://career.acme.de/stellenangebote/aktuelle-stellenangebote.html")
