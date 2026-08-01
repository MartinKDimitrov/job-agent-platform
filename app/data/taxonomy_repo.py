"""Read side of the occupation taxonomy — the queries the hierarchical onboarding drills through:
vertical -> ISCO group (subcategory) -> occupation -> its essential/optional skills, plus a
free-text occupation search for the picker. Language-aware: labels come back in the caller's UI
language (bg/en), falling back to the other when a translation is missing."""
from collections import Counter

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .models import OccupationGroup, Occupation, OccupationSkill, TaxonomySkill, NapooDirection


import re as _re
# The first learning-outcome units of EVERY ДОС are generic (health-and-safety, entrepreneurship,
# communication, environment) — reworded per document, so exact-frequency won't catch them. Filter
# by topic keyword so what remains is the FIELD-specific competency.
_NAPOO_GENERIC = _re.compile(
    r"безопасн|аварий|първа помощ|злополук|предприемач|икономическ|пазарн|бизнес план|"
    r"околната среда|отпадъц|комуникац|нормативни акт|трудовоправн|застраховане срещу|"
    r"чужд език|дигитал(ни|на) компетентн", _re.I)


def napoo_skills_for_vertical(db: Session, vertical: str, limit: int = 40) -> list[str]:
    """Official Bulgarian ПОО competencies (НАПОО умения) for a profile's field — the FIELD-specific
    ones, dropping the generic safety/entrepreneurship/communication units that open every ДОС.
    Descriptive statements for display/CV; not matchable tags."""
    if not vertical:
        return []
    dirs = [d for d in db.execute(
        select(NapooDirection).where(NapooDirection.vertical == vertical)).scalars()]
    seen, out = set(), []
    for d in dirs:
        for s in d.skills or []:
            k = s.strip(); kl = k.lower()
            if len(k) >= 6 and kl not in seen and not _NAPOO_GENERIC.search(kl):
                seen.add(kl); out.append(k)
    return out[:limit]


def _clean(skills, limit):
    seen, out = set(), []
    for s in skills or []:
        k = s.strip(); kl = k.lower()
        if len(k) >= 6 and kl not in seen and not _NAPOO_GENERIC.search(kl):
            seen.add(kl); out.append(k)
    return out[:limit]


def napoo_skills_for_direction(db: Session, name: str, limit: int = 40) -> list[str]:
    """The specific НАПОО direction's field competencies (generic units filtered)."""
    if not name:
        return []
    d = db.execute(select(NapooDirection).where(NapooDirection.name == name)).scalars().first()
    return _clean(d.skills if d else [], limit)


def napoo_skills_for_profile(db: Session, profile, limit: int = 40) -> list[str]:
    """Official ПОО competencies for a profile — the specific profession's direction first (matched
    by name at onboarding), falling back to the vertical-wide competencies when there's no direction."""
    d = napoo_skills_for_direction(db, getattr(profile, "napoo_direction", "") or "", limit)
    return d or napoo_skills_for_vertical(db, getattr(profile, "vertical", "") or "", limit)


def _label(row, lang: str) -> str:
    """The row's label in `lang`; ru/uk (not in ESCO) and any gap fall back to en, then any label."""
    labels = row.labels or {}
    return labels.get(lang) or labels.get("en") or next(iter(labels.values()), "")


def verticals(db: Session) -> list[str]:
    return [v for (v,) in db.execute(
        select(Occupation.vertical).where(Occupation.vertical != "")
        .distinct().order_by(Occupation.vertical)).all()]


def groups(db: Session, vertical: str, parent_code: str | None = None,
           lang: str = "bg") -> list[dict]:
    """Subcategory groups within a vertical, labelled in `lang`. parent_code None -> the top groups
    of that vertical (those whose parent isn't itself in the vertical), else the direct children.
    A group also reports whether it has occupations directly under it (a leaf the picker can open)."""
    q = select(OccupationGroup).where(OccupationGroup.vertical == vertical)
    if parent_code is None:
        codes = {c for (c,) in db.execute(
            select(OccupationGroup.isco_code).where(OccupationGroup.vertical == vertical)).all()}
        rows = [g for g in db.execute(q).scalars() if g.parent_code not in codes]
    else:
        rows = list(db.execute(q.where(OccupationGroup.parent_code == parent_code)).scalars())
    rows.sort(key=lambda g: g.isco_code)
    with_occ = {c for (c,) in db.execute(
        select(Occupation.isco_code).where(Occupation.vertical == vertical).distinct()).all()}
    has_children = {g.parent_code for g in db.execute(q).scalars()}
    return [{"isco_code": g.isco_code, "level": g.level, "label": _label(g, lang),
             "has_occupations": g.isco_code in with_occ,
             "has_children": g.isco_code in has_children} for g in rows]


def leaf_groups(db: Session, vertical: str, lang: str = "bg") -> list[dict]:
    """Every group in a vertical that has occupations directly under it — the flat subcategory
    list the onboarding shows after the user picks a vertical (intermediate ISCO levels skipped)."""
    counts = dict(db.execute(
        select(Occupation.isco_code, func.count()).where(Occupation.vertical == vertical)
        .group_by(Occupation.isco_code)).all())
    if not counts:
        return []
    rows = db.execute(select(OccupationGroup).where(
        OccupationGroup.vertical == vertical, OccupationGroup.isco_code.in_(counts))).scalars()
    out = [{"isco_code": g.isco_code, "label": _label(g, lang), "count": counts.get(g.isco_code, 0)}
           for g in rows]
    out.sort(key=lambda g: g["label"].lower())
    return out


def _primary_nkpd(o: Occupation) -> dict | None:
    """The best official NKPD position for an occupation: the exact ('Точно') match if any, else
    the first. Carries the min qualification level (0-9) the BG onboarding shows."""
    items = o.nkpd or []
    if not items:
        return None
    return next((x for x in items if x.get("rel") == "Точно"), items[0])


def occupations(db: Session, isco_code: str, lang: str = "bg") -> list[dict]:
    """Occupations that hang off a leaf ISCO group, labelled in `lang`. For Bulgarian, each also
    carries its official NKPD-2011 qualification level + title (BG-market overlay; ESCO stays the
    label backbone for every language)."""
    out = []
    for o in db.execute(select(Occupation).where(Occupation.isco_code == isco_code)).scalars():
        d = {"id": o.id, "esco_uri": o.esco_uri, "label": _label(o, lang)}
        if lang == "bg":
            pn = _primary_nkpd(o)
            if pn:
                d["level"] = pn.get("level") or ""
                d["official"] = pn.get("title") or ""
        out.append(d)
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
    """Free-text occupation search for the picker — matches ANY language's label (labels is JSON,
    so we filter in Python; the occupation set is small). Prefers a prefix hit on the UI-language
    label, then any substring."""
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []
    out = []
    for o in db.execute(select(Occupation)).scalars():
        vals = [v for v in (o.labels or {}).values()]
        if not any(q in v.lower() for v in vals):
            continue
        disp = _label(o, lang)
        rank = 0 if disp.lower().startswith(q) else (1 if any(v.lower().startswith(q) for v in vals) else 2)
        out.append((rank, disp.lower(), {"id": o.id, "esco_uri": o.esco_uri, "label": disp,
                                         "vertical": o.vertical, "isco_code": o.isco_code}))
    out.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in out[:limit]]
