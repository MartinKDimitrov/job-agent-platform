"""Arbeitsagentur (DE) adapter — public Jobsuche API, search + paced details."""
import app.data.sources.arbeitsagentur as ba
from app.application.usecases.search import PROFILE_SOURCES

HIT = {
    "refnr": "13644-151818-S",
    "titel": "Android-Entwickler:in (m/w/d)",
    "beruf": "Anwendungsprogrammierer/in",
    "arbeitgeber": "DIVERA",
    "arbeitsort": {"ort": "Wuppertal", "region": "Nordrhein-Westfalen"},
    "aktuelleVeroeffentlichungsdatum": "2026-07-03",
    "externeUrl": "https://www.get-in-it.de/jobsuche/p151818",
}
DETAIL = {"stellenangebotsBeschreibung": "## Aufgaben\n- Kotlin und Java\n- CI/CD Pipelines"}


def _mock(monkeypatch, hits=None, detail=DETAIL):
    calls = {"search": 0, "detail": 0}

    def fake(url, params=None, headers=None):
        assert headers and headers.get("X-API-Key") == "jobboerse-jobsuche"
        if "jobdetails" in url:
            calls["detail"] += 1
            return detail
        calls["search"] += 1
        return {"stellenangebote": hits if hits is not None else [HIT]}
    monkeypatch.setattr(ba, "fetch_json", fake)
    return calls


def test_maps_search_plus_details(monkeypatch):
    _mock(monkeypatch)
    (p,) = ba.fetch(search_terms=["android"], sleep=lambda s: None)
    assert p.source_kind == "board_api" and p.external_id == "13644-151818-S"
    assert p.title.startswith("Android-Entwickler")
    assert p.company == "DIVERA"
    assert p.location == "Wuppertal, Nordrhein-Westfalen, Germany"
    assert p.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/13644-151818-S"
    assert p.apply_url == "https://www.get-in-it.de/jobsuche/p151818"   # externeUrl wins
    assert "Kotlin" in p.description
    assert p.posted_at is not None and p.posted_at.month == 7


def test_job_page_is_apply_fallback(monkeypatch):
    hit = dict(HIT)
    hit.pop("externeUrl")
    _mock(monkeypatch, hits=[hit])
    (p,) = ba.fetch(search_terms=["android"], sleep=lambda s: None)
    assert p.apply_url == p.url


def test_descriptionless_postings_are_skipped(monkeypatch):
    _mock(monkeypatch, detail={})
    assert ba.fetch(search_terms=["android"], sleep=lambda s: None) == []


def test_duplicates_across_terms_fetch_details_once(monkeypatch):
    calls = _mock(monkeypatch)
    out = ba.fetch(search_terms=["android", "kotlin"], sleep=lambda s: None)
    assert len(out) == 1 and calls["detail"] == 1


def test_wired_as_targeted_profile_source():
    assert "arbeitsagentur_targeted" in [n for n, _ in PROFILE_SOURCES]
