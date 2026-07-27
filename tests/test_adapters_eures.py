"""EURES — EU employment portal public search API adapter (POST per country -> RawPostings)."""
import app.data.sources.eures as eu


def _jv(i, lang="bg"):
    return {"id": f"ID{i}", "title": f"Продавач {i}",
            "description": "Дълго описание на позицията, което покрива минималния праг за скор тук.",
            "creationDate": 1784581204574, "locationMap": {"BG": ["BG333"]},
            "employer": {"name": "Acme EOOD"}, "availableLanguages": [lang], "translations": {}}


def test_fetch_per_country_and_dedups(monkeypatch):
    calls = []

    def fake(url, body, **k):
        cc = body.get("locationCodes")[0]
        calls.append(cc)
        return {"numberRecords": 3, "jvs": [_jv(f"{cc}1"), _jv(f"{cc}1"), _jv(f"{cc}2")]}  # dup within
    monkeypatch.setattr(eu, "post_json", fake)
    posts = eu.fetch(countries=("bg", "ro"), pages=1, sleep=lambda *_: None)
    assert len(posts) == 4                                # 2 unique per country × 2 countries
    assert calls == ["bg", "ro"]                          # one call per country
    p = next(p for p in posts if p.external_id == "eures:IDbg1")
    assert p.company == "Acme EOOD" and p.location == "BG" and p.posted_at.year == 2026
    assert p.url == "https://europa.eu/eures/portal/jv-se/jv-details/IDbg1"


def test_prefers_english_translation(monkeypatch):
    jv = _jv(9)
    jv["translations"] = {"en": {"title": "Sales assistant",
                                 "description": "A sufficiently long English description here to pass the gate."}}
    monkeypatch.setattr(eu, "post_json", lambda url, body, **k: {"jvs": [jv]})
    posts = eu.fetch(countries=("bg",), pages=1, sleep=lambda *_: None)
    assert posts and "English description" in posts[0].description


def test_short_description_and_missing_id_dropped(monkeypatch):
    bad = [{"id": "x", "title": "T", "description": "too short"},
           {"id": None, "title": "No id", "description": "x" * 60}]
    monkeypatch.setattr(eu, "post_json", lambda url, body, **k: {"jvs": bad})
    assert eu.fetch(countries=("bg",), pages=1, sleep=lambda *_: None) == []
