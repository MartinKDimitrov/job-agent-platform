"""SAP SuccessFactors adapter — Career Site Builder HTML (list tiles + detail scrape)."""
import app.data.sources.successfactors as sf
import app.data.ats_detect as ats

LISTING = ('<ul>'
           '<li class="job-tile job-id-1" data-url="/job/Berlin-Android-Dev/1/">x</li>'
           '<li class="job-tile job-id-2" data-url="/job/x/2/">y</li>'
           '</ul>')
DETAIL1 = ('<h1 itemprop="title">Android Developer</h1>'
           '<span class="jobdescription"><p>Requirements:</p><ul><li>Kotlin and Compose</li>'
           '<li>REST APIs</li></ul></span>'
           '<div class="job-footer">Job Segment: Mobile, Engineering</div>')
DETAIL2 = '<h1 itemprop="title">No Desc</h1><span class="jobdescription"></span>'


def _mock(monkeypatch):
    def fake(url):
        if url.endswith("/tile-search-results/?q="):
            return LISTING
        if "/job/Berlin-Android-Dev/1/" in url:
            return DETAIL1
        return DETAIL2
    monkeypatch.setattr(sf, "fetch_text", fake)


def test_lists_and_scrapes_detail(monkeypatch):
    _mock(monkeypatch)
    out = sf.fetch("https://jobs.sap.com", company_name="SAP", sleep=lambda s: None)
    assert len(out) == 1                              # DETAIL2 (empty desc) is skipped
    p = out[0]
    assert p.source_kind == "html" and p.external_id == "1"
    assert p.title == "Android Developer" and p.company == "SAP"
    assert "Kotlin" in p.description and "Job Segment" not in p.description  # footer trimmed
    assert "<p>" not in p.description                 # HTML stripped
    assert p.url == "https://jobs.sap.com/job/Berlin-Android-Dev/1/"


def test_empty_base(monkeypatch):
    assert sf.fetch("") == []


# ---- detection ----
def test_successfactors_careers_scan(monkeypatch):
    html = '<div>... <li class="job-tile" data-url="/job/x/1/">..</li></div>'
    monkeypatch.setattr(ats, "fetch_text", lambda url: html)
    assert ats.scan_careers_page("https://jobs.sap.com/") == ("successfactors", "https://jobs.sap.com")


def test_successfactors_probe(monkeypatch):
    monkeypatch.setattr(ats, "fetch_text", lambda url: '<li class="job-tile">x</li>')
    assert ats._probe_successfactors("https://jobs.sap.com") is True
    monkeypatch.setattr(ats, "fetch_text", lambda url: "<html>nothing</html>")
    assert ats._probe_successfactors("https://x.com") is False
