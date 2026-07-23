"""France Travail (FR) adapter — OAuth client-credentials + targeted search."""
import app.data.sources.francetravail as ft
from app.application.usecases.search import PROFILE_SOURCES
from app.core.config import settings

OFFRE = {
    "id": "197XKZM",
    "intitule": "Développeur Android (H/F)",
    "description": "Exigences:\n- Kotlin et Jetpack Compose\n- CI/CD",
    "entreprise": {"nom": "Capgemini"},
    "lieuTravail": {"libelle": "75 - PARIS 09"},
    "dateCreation": "2026-07-20T08:15:00Z",
    "origineOffre": {"urlOrigine": "https://www.capgemini.com/jobs/197"},
}


def _configure(monkeypatch, cid="id", secret="s"):
    monkeypatch.setattr(settings, "francetravail_client_id", cid)
    monkeypatch.setattr(settings, "francetravail_client_secret", secret)
    monkeypatch.setattr(ft, "_get_token", lambda: "tok")


def test_noop_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "francetravail_client_id", "")
    monkeypatch.setattr(settings, "francetravail_client_secret", "")
    assert ft.fetch(search_terms=["android"]) == []


def test_maps_offres_to_raw_postings(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(ft, "_search", lambda term, token: [OFFRE])
    (p,) = ft.fetch(search_terms=["android"])
    assert p.source_kind == "board_api" and p.external_id == "197XKZM"
    assert p.title.startswith("Développeur Android")
    assert p.company == "Capgemini"
    assert p.location == "75 - PARIS 09, France"
    assert p.url.endswith("/detail/197XKZM")
    assert p.apply_url == "https://www.capgemini.com/jobs/197"   # employer origin wins
    assert "Kotlin" in p.description
    assert p.posted_at is not None and p.posted_at.day == 20


def test_page_is_apply_fallback_and_dedup(monkeypatch):
    _configure(monkeypatch)
    offre = dict(OFFRE)
    offre["origineOffre"] = {}
    monkeypatch.setattr(ft, "_search", lambda term, token: [offre, offre])
    out = ft.fetch(search_terms=["android", "kotlin"])
    assert len(out) == 1 and out[0].apply_url == out[0].url


def test_dead_token_means_empty(monkeypatch):
    monkeypatch.setattr(settings, "francetravail_client_id", "id")
    monkeypatch.setattr(settings, "francetravail_client_secret", "s")
    monkeypatch.setattr(ft, "_get_token", lambda: "")
    assert ft.fetch(search_terms=["android"]) == []


def test_wired_as_targeted_profile_source():
    assert "francetravail_targeted" in [n for n, _ in PROFILE_SOURCES]
