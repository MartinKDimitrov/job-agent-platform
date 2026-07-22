"""SmartRecruiters / Recruitee / Personio adapters (16в) — shapes verified live 2026-07."""
import app.data.sources.smartrecruiters as sr
import app.data.sources.recruitee as rc
import app.data.sources.personio as pe

# ---- SmartRecruiters ----
SR_LIST = {"totalFound": 2, "content": [
    {"id": "111", "name": "Android Developer", "releasedDate": "2026-06-24T10:00:11.853Z",
     "location": {"city": "Sofia", "country": "bg", "remote": False,
                  "fullLocation": "Sofia, Bulgaria"},
     "company": {"name": "Acme"}, "department": {"label": "Engineering"}},
    {"id": "222", "name": "QA Engineer", "releasedDate": "",
     "location": {"remote": True}},
]}
SR_DETAIL = {
    "111": {"postingUrl": "https://jobs.smartrecruiters.com/Acme/111-android",
            "applyUrl": "https://jobs.smartrecruiters.com/Acme/111-android?oga=true",
            "jobAd": {"sections": {
                "companyDescription": {"text": "<p>We are a mission-driven unicorn.</p>"},
                "jobDescription": {"text": "<p>Build Android apps.</p>"},
                "qualifications": {"text": "<ul><li>Kotlin experience</li></ul>"},
                "additionalInformation": {"text": "<p>Multisport card and snacks.</p>"}}}},
    "222": {"postingUrl": "", "applyUrl": "", "jobAd": {"sections": {}}},
}


def _mock_sr(monkeypatch):
    def fake_json(url, params=None, timeout=15.0, browser=False):
        if url.endswith("/postings"):
            return SR_LIST
        return SR_DETAIL.get(url.rsplit("/", 1)[-1])
    monkeypatch.setattr(sr, "fetch_json", fake_json)


def test_sr_maps_fields_and_skips_marketing_and_benefits(monkeypatch):
    _mock_sr(monkeypatch)
    posts = sr.fetch("Acme", company_name="Acme", detail_delay=0)
    assert len(posts) == 2
    p = posts[0]
    assert p.title == "Android Developer" and p.location == "Sofia, Bulgaria"
    assert p.url.endswith("/111-android") and "oga=true" in p.apply_url
    assert "Build Android apps" in p.description
    assert "Requirements:" in p.description and "Kotlin experience" in p.description
    assert "unicorn" not in p.description            # companyDescription skipped
    assert "Multisport" not in p.description         # additionalInformation skipped
    assert posts[1].location == "Remote"
    assert posts[1].url.endswith("/Acme/222")        # constructed when detail is bare


def test_sr_dead_company(monkeypatch):
    monkeypatch.setattr(sr, "fetch_json", lambda *a, **k: None)
    assert sr.fetch("ghost") == []


# ---- Recruitee ----
RC_OFFERS = {"offers": [
    {"id": 9, "title": "Backend Developer", "company_name": "Acme",
     "careers_url": "https://acme.recruitee.com/o/backend-developer",
     "careers_apply_url": "https://acme.recruitee.com/o/backend-developer/c/new",
     "location": "Sofia, Bulgaria", "remote": False,
     "created_at": "2026-07-01 10:19:52 UTC",
     "description": "<p>Join our backend team.</p>",
     "requirements": "<ul><li>Python experience</li></ul>"},
    {"id": 10, "title": "Support", "careers_url": "https://acme.recruitee.com/o/support",
     "remote": True, "description": "", "requirements": ""},
]}


def test_recruitee_maps_fields(monkeypatch):
    monkeypatch.setattr(rc, "fetch_json", lambda *a, **k: RC_OFFERS)
    posts = rc.fetch("acme")
    assert len(posts) == 2
    p = posts[0]
    assert p.title == "Backend Developer" and p.company == "Acme"
    assert p.location == "Sofia, Bulgaria" and p.posted_at is not None
    assert p.apply_url.endswith("/c/new")
    assert "Requirements:" in p.description and "Python experience" in p.description
    assert posts[1].location == "Remote"


def test_recruitee_dead(monkeypatch):
    monkeypatch.setattr(rc, "fetch_json", lambda *a, **k: None)
    assert rc.fetch("ghost") == []


# ---- Personio ----
PERSONIO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs><position>
  <id>1822268</id><office>Sofia</office><name>DevOps Engineer</name>
  <recruitingCategory>Engineering</recruitingCategory>
  <jobDescriptions>
    <jobDescription><name>Your tasks</name><value><![CDATA[<p>Run our clusters.</p>]]></value></jobDescription>
    <jobDescription><name>Your profile</name><value><![CDATA[<ul><li>Kubernetes experience</li></ul>]]></value></jobDescription>
  </jobDescriptions>
</position></workzag-jobs>"""


def test_personio_parses_positions(monkeypatch):
    calls = []
    def fake_text(url, params=None, timeout=15.0):
        calls.append(url)
        return PERSONIO_XML if url == "https://acme.jobs.personio.de/xml" else None
    monkeypatch.setattr(pe, "fetch_text", fake_text)
    posts = pe.fetch("acme", company_name="Acme")
    assert len(posts) == 1
    p = posts[0]
    assert p.title == "DevOps Engineer" and p.company == "Acme" and p.location == "Sofia"
    assert p.url == "https://acme.jobs.personio.de/job/1822268"
    assert "Your profile:" in p.description and "Kubernetes experience" in p.description


def test_personio_falls_back_to_com(monkeypatch):
    def fake_text(url, params=None, timeout=15.0):
        return PERSONIO_XML if url == "https://acme.jobs.personio.com/xml" else None
    monkeypatch.setattr(pe, "fetch_text", fake_text)
    assert pe.fetch("acme")[0].url.startswith("https://acme.jobs.personio.com/")


def test_personio_dead(monkeypatch):
    monkeypatch.setattr(pe, "fetch_text", lambda *a, **k: None)
    assert pe.fetch("ghost") == []
