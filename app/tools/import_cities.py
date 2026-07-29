"""Load the city gazetteer from a GeoNames dump (cities5000.txt) — every European settlement with
population >= 10000. Stores the endonym + ASCII/EN name and population for the location
autocomplete. Localized per-language names (Cyrillic/Greek) are a later enrichment (alternateNames).

    # one-time: download + unzip cities5000 from https://download.geonames.org/export/dump/
    python -m app.tools.import_cities /path/to/cities5000.txt
"""
import sys

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..data.db import SessionLocal, engine, Base
from ..data.models import City

MIN_POP = 10000

# European ISO-3166-1 alpha-2 -> English country name (matches the onboarding country dropdown).
EUROPE: dict[str, str] = {
    "AL": "Albania", "AD": "Andorra", "AT": "Austria", "BY": "Belarus", "BE": "Belgium",
    "BA": "Bosnia and Herzegovina", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus",
    "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia", "FI": "Finland", "FR": "France",
    "DE": "Germany", "GR": "Greece", "HU": "Hungary", "IS": "Iceland", "IE": "Ireland",
    "IT": "Italy", "XK": "Kosovo", "LV": "Latvia", "LI": "Liechtenstein", "LT": "Lithuania",
    "LU": "Luxembourg", "MT": "Malta", "MD": "Moldova", "MC": "Monaco", "ME": "Montenegro",
    "NL": "Netherlands", "MK": "North Macedonia", "NO": "Norway", "PL": "Poland",
    "PT": "Portugal", "RO": "Romania", "RU": "Russia", "SM": "San Marino", "RS": "Serbia",
    "SK": "Slovakia", "SI": "Slovenia", "ES": "Spain", "SE": "Sweden", "CH": "Switzerland",
    "TR": "Turkey", "UA": "Ukraine", "GB": "United Kingdom", "VA": "Vatican",
}


def run(txt_path: str, session_factory=SessionLocal, min_pop: int = MIN_POP) -> dict:
    Base.metadata.create_all(bind=engine)
    rows = []
    with open(txt_path, encoding="utf-8") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 15:
                continue
            code = c[8]
            if code not in EUROPE:
                continue
            try:
                pop = int(c[14] or 0)
            except ValueError:
                continue
            if pop < min_pop:
                continue
            name, ascii_name = c[1], (c[2] or c[1])
            rows.append({"geoname_id": int(c[0]), "country": EUROPE[code], "country_code": code,
                         "name_en": ascii_name[:255], "names": {"en": name[:255]}, "population": pop})
    with session_factory() as db:  # type: Session
        db.execute(delete(City))                       # reference data — rebuild cleanly
        db.commit()
        for i in range(0, len(rows), 1000):
            db.bulk_insert_mappings(City, rows[i:i + 1000])
            db.commit()
    by_country: dict[str, int] = {}
    for r in rows:
        by_country[r["country"]] = by_country.get(r["country"], 0) + 1
    stats = {"cities": len(rows), "countries": len(by_country)}
    print(f"DONE {stats}")
    print("top:", sorted(by_country.items(), key=lambda x: -x[1])[:8])
    return stats


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "cities5000.txt")
