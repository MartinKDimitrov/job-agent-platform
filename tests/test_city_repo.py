"""City gazetteer read side: population-ranked autocomplete, curated fallback when empty."""
from app.data.db import SessionLocal
from app.data.models import City
from app.data import city_repo

_FALLBACK = {"Bulgaria": ["Sofia", "Plovdiv"], "Germany": ["Berlin"]}


def _seed(db):
    db.add_all([
        City(geoname_id=1, country="Bulgaria", country_code="BG", name_en="Sofia",
             names={"en": "Sofia"}, population=1200000),
        City(geoname_id=2, country="Bulgaria", country_code="BG", name_en="Plovdiv",
             names={"en": "Plovdiv"}, population=340000),
        City(geoname_id=3, country="Germany", country_code="DE", name_en="Berlin",
             names={"en": "Berlin"}, population=3600000),
    ])
    db.commit()


def test_search_ranks_by_population_and_prefix():
    with SessionLocal() as db:
        _seed(db)
        top = [c["name"] for c in city_repo.search(db, "Bulgaria", "")]
        assert top == ["Sofia", "Plovdiv"]                 # bigger first, no query
        assert [c["name"] for c in city_repo.search(db, "Bulgaria", "plov")] == ["Plovdiv"]
        assert city_repo.search(db, "Germany", "ber")[0]["name"] == "Berlin"


def test_countries_lists_gazetteer_with_bulgaria_first():
    with SessionLocal() as db:
        _seed(db)
        assert city_repo.countries(db) == ["Bulgaria", "Germany"]


def test_falls_back_to_curated_when_empty():
    with SessionLocal() as db:
        # no City rows -> curated fallback list is used
        assert city_repo.search(db, "Bulgaria", "sof", fallback=_FALLBACK)[0]["name"] == "Sofia"
        assert city_repo.countries(db, _FALLBACK) == ["Bulgaria", "Germany"]
