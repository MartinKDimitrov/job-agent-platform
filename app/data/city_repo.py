"""Read side of the city gazetteer — the location autocomplete. Queries the GeoNames-backed City
table (all European settlements > 10k, multilingual, ranked by population); until that's loaded it
serves a curated fallback list so onboarding works from day one. Language-aware with en fallback."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import City


def countries(db: Session, fallback: dict | None = None) -> list[str]:
    """Countries available in the gazetteer (for the onboarding dropdown); curated keys until it
    loads. Bulgaria floats to the top (primary market), the rest alphabetical."""
    rows = [c for (c,) in db.execute(select(City.country).distinct()).all()]
    names = rows or list(fallback or {})
    names = sorted(set(names))
    return (["Bulgaria"] if "Bulgaria" in names else []) + [n for n in names if n != "Bulgaria"]


def search(db: Session, country: str, q: str, lang: str = "bg",
           fallback: dict | None = None, limit: int = 15) -> list[dict]:
    q = (q or "").strip().lower()
    rows = db.execute(
        select(City).where(City.country == country)
        .order_by(City.population.desc()).limit(2000)).scalars().all()
    if rows:
        scored = []
        for c in rows:
            names = c.names or {}
            disp = names.get(lang) or names.get("en") or c.name_en
            hay = [c.name_en.lower()] + [v.lower() for v in names.values()]
            if q and not any(q in h for h in hay):
                continue
            rank = 0 if disp.lower().startswith(q) else 1
            scored.append((rank, -(c.population or 0), {"name": disp}))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [r for _, _, r in scored[:limit]]
    # fallback: curated {country: [city, …]} while the gazetteer isn't loaded yet
    cities = (fallback or {}).get(country, [])
    hits = [{"name": c} for c in cities if not q or q in c.lower()]
    return hits[:limit]
