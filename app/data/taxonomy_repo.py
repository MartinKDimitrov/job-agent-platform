"""Read side of the occupation taxonomy — the queries the hierarchical onboarding drills through:
vertical -> ISCO group (subcategory) -> occupation -> its essential/optional skills, plus a
free-text occupation search for the picker. Language-aware: labels come back in the caller's UI
language (bg/en), falling back to the other when a translation is missing."""
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .models import OccupationGroup, Occupation, OccupationSkill, TaxonomySkill


def _label(row, lang: str) -> str:
    """The row's label in `lang`, falling back to the other language when empty."""
    primary, other = (row.label_bg, row.label_en) if lang == "bg" else (row.label_en, row.label_bg)
    return primary or other or ""


def verticals(db: Session) -> list[str]:
    return [v for (v,) in db.execute(
        select(Occupation.vertical).where(Occupation.vertical != "")
        .distinct().order_by(Occupation.vertical)).all()]


def groups(db: Session, vertical: str, parent_code: str | None = None) -> list[dict]:
    """Subcategory groups within a vertical. parent_code None -> the top groups of that vertical
    (those whose parent isn't itself in the vertical), otherwise the direct children."""
    q = select(OccupationGroup).where(OccupationGroup.vertical == vertical)
    if parent_code is None:
        codes = {c for (c,) in db.execute(
            select(OccupationGroup.isco_code).where(OccupationGroup.vertical == vertical)).all()}
        rows = [g for g in db.execute(q).scalars() if g.parent_code not in codes]
    else:
        rows = list(db.execute(q.where(OccupationGroup.parent_code == parent_code)).scalars())
    rows.sort(key=lambda g: g.isco_code)
    return [{"isco_code": g.isco_code, "level": g.level} for g in rows]


def occupations(db: Session, isco_code: str, lang: str = "bg") -> list[dict]:
    """Occupations that hang off a leaf ISCO group, labelled in `lang`."""
    rows = db.execute(select(Occupation).where(Occupation.isco_code == isco_code)).scalars()
    out = [{"id": o.id, "esco_uri": o.esco_uri, "label": _label(o, lang)} for o in rows]
    out.sort(key=lambda o: o["label"].lower())
    return out


def occupation_skills(db: Session, occupation_id: int, lang: str = "bg") -> list[dict]:
    """An occupation's skills, essential first, labelled in `lang` — the onboarding pre-fill."""
    rows = db.execute(
        select(OccupationSkill, TaxonomySkill)
        .join(TaxonomySkill, OccupationSkill.skill_id == TaxonomySkill.id)
        .where(OccupationSkill.occupation_id == occupation_id)).all()
    out = [{"label": _label(sk, lang), "essential": os.essential} for os, sk in rows]
    out.sort(key=lambda s: (not s["essential"], s["label"].lower()))
    return out


def search_occupations(db: Session, query: str, lang: str = "bg", limit: int = 20) -> list[dict]:
    """Free-text occupation search for the picker (matches either language)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    like = f"%{q}%"
    rows = db.execute(
        select(Occupation).where(
            func.lower(Occupation.label_en).like(like) | func.lower(Occupation.label_bg).like(like))
        .limit(limit)).scalars()
    out = [{"id": o.id, "esco_uri": o.esco_uri, "label": _label(o, lang),
            "vertical": o.vertical, "isco_code": o.isco_code} for o in rows]
    out.sort(key=lambda o: o["label"].lower())
    return out
