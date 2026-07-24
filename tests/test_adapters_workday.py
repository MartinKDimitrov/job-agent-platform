"""Workday adapter — enterprise CXS API (list POST + paced detail GETs) + detection."""
import app.data.sources.workday as wd
import app.data.ats_detect as ats

BASE = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers"
LISTING = {"total": 2, "jobPostings": [
    {"title": "Android Engineer", "externalPath": "/job/Berlin/Android_JR1",
     "locationsText": "Germany, Berlin", "bulletFields": ["JR1"]},
    {"title": "No Desc Job", "externalPath": "/job/x/JR2", "bulletFields": ["JR2"]},
]}
DETAIL1 = {"jobPostingInfo": {"title": "Android Engineer", "jobReqId": "JR1",
    "jobDescription": "<p>Requirements:</p><ul><li>Kotlin and Compose</li></ul>",
    "location": "Germany, Berlin", "startDate": "2026-07-20",
    "externalUrl": "https://acme.wd5.myworkdayjobs.com/AcmeCareers/job/Berlin/Android_JR1"}}


def _mock(monkeypatch, detail=DETAIL1):
    monkeypatch.setattr(wd, "post_json", lambda url, body: LISTING)
    def fake_get(url, params=None):
        return detail if "Android_JR1" in url else {"jobPostingInfo": {}}  # JR2 = no desc
    monkeypatch.setattr(wd, "fetch_json", fake_get)


def test_maps_listing_plus_details(monkeypatch):
    _mock(monkeypatch)
    out = wd.fetch(BASE, company_name="Acme", sleep=lambda s: None)
    assert len(out) == 1                         # JR2 (no description) is skipped
    p = out[0]
    assert p.source_kind == "ats_api" and p.external_id == "JR1"
    assert p.title == "Android Engineer" and p.company == "Acme"
    assert p.location == "Germany, Berlin"
    assert "Kotlin" in p.description and "<p>" not in p.description   # HTML stripped
    assert p.url.endswith("/Android_JR1") and p.apply_url == p.url
    assert p.posted_at is not None and p.posted_at.month == 7


def test_empty_base_and_bad_payload(monkeypatch):
    assert wd.fetch("") == []
    monkeypatch.setattr(wd, "post_json", lambda url, body: None)
    assert wd.fetch(BASE) == []


# ---- detection ----
def test_workday_careers_scan_builds_cxs_base(monkeypatch):
    html = 'x <a href="https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/y">z</a>'
    monkeypatch.setattr(ats, "fetch_text", lambda url: html)
    res = ats.scan_careers_page("https://www.nvidia.com/careers")
    assert res == ("workday",
                   "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite")


def test_workday_scan_ignores_generic_path_words(monkeypatch):
    html = 'https://acme.wd3.myworkdayjobs.com/en-US/job/x'   # 'en-US' is not a real site
    monkeypatch.setattr(ats, "fetch_text", lambda url: html)
    assert ats.scan_careers_page("https://acme.com/careers") is None


def test_workday_tenant_identity_check():
    # a careers page can link a subsidiary's Workday (Deutsche Börse -> ISS) — reject those
    ok = "https://qiagen.wd502.myworkdayjobs.com/wday/cxs/qiagen/QIAGEN"
    bad = "https://issgovernance.wd1.myworkdayjobs.com/wday/cxs/issgovernance/ISScareers"
    assert ats._workday_tenant_ok("Qiagen", ok) is True
    assert ats._workday_tenant_ok("Air Liquide", ok.replace("qiagen", "airliquidehr")) is True
    assert ats._workday_tenant_ok("Pernod Ricard", ok.replace("qiagen", "pernodricard")) is True
    assert ats._workday_tenant_ok("Deutsche Börse", bad) is False


def test_workday_probe_checks_jobpostings(monkeypatch):
    from app.data.sources import http as _http
    monkeypatch.setattr("app.data.sources.http.post_json",
                        lambda url, body: {"jobPostings": []})
    assert ats._probe_workday(BASE) is True
    monkeypatch.setattr("app.data.sources.http.post_json", lambda url, body: {})
    assert ats._probe_workday(BASE) is False
