"""JobTech / Platsbanken (SE) adapter — the first EU-board source (open API)."""
import app.data.sources.jobtech as jt
from app.application.usecases.search import PROFILE_SOURCES


def _hit(hid="31219871", headline="Android Developer", url_apply="https://coop.se/apply"):
    return {
        "id": hid,
        "headline": headline,
        "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{hid}",
        "publication_date": "2026-06-26T10:55:10",
        "description": {"text": "Requirements:\n- Kotlin and Jetpack Compose\n- CI/CD"},
        "employer": {"name": "Coop Sverige"},
        "workplace_address": {"municipality": "Solna", "region": "Stockholms län"},
        "application_details": {"url": url_apply},
    }


def test_maps_hits_to_raw_postings(monkeypatch):
    monkeypatch.setattr(jt, "fetch_json",
                        lambda url, params=None: {"hits": [_hit()]})
    (p,) = jt.fetch(search_terms=["android"])
    assert p.source_kind == "board_api" and p.external_id == "31219871"
    assert p.title == "Android Developer" and p.company == "Coop Sverige"
    assert p.location == "Solna, Stockholms län, Sweden"
    assert p.url.endswith("/annonser/31219871")
    assert p.apply_url == "https://coop.se/apply"        # employer's direct link wins
    assert "Kotlin" in p.description
    assert p.posted_at is not None and p.posted_at.year == 2026


def test_webpage_url_is_apply_fallback(monkeypatch):
    hit = _hit()
    hit["application_details"] = {"url": None}
    monkeypatch.setattr(jt, "fetch_json", lambda url, params=None: {"hits": [hit]})
    (p,) = jt.fetch(search_terms=["android"])
    assert p.apply_url == p.url


def test_duplicate_ids_across_terms_collapse(monkeypatch):
    monkeypatch.setattr(jt, "fetch_json",
                        lambda url, params=None: {"hits": [_hit(), _hit()]})
    assert len(jt.fetch(search_terms=["android", "kotlin"])) == 1


def test_bad_payloads_are_safe(monkeypatch):
    monkeypatch.setattr(jt, "fetch_json", lambda url, params=None: None)
    assert jt.fetch(search_terms=["android"]) == []
    assert jt.fetch(search_terms=None) == []


def test_wired_as_targeted_profile_source():
    assert "jobtech_targeted" in [n for n, _ in PROFILE_SOURCES]
