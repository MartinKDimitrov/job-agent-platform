"""The onboarding drill-down queries over a seeded occupation taxonomy (vertical -> group ->
occupation -> skills), language-aware with fallback."""
from app.data.db import SessionLocal
from app.data.models import OccupationGroup, Occupation, TaxonomySkill, OccupationSkill
from app.data import taxonomy_repo as tx


def _seed(db):
    db.add_all([
        OccupationGroup(isco_code="241", parent_code="24", level=3, vertical="finance",
                        labels={"en": "Finance professionals", "bg": "Финансови специалисти"}),
        OccupationGroup(isco_code="2411", parent_code="241", level=4, vertical="finance",
                        labels={"en": "Accountants", "bg": "Одитори и счетоводители"}),
    ])
    occ = Occupation(esco_uri="esco/occ/accountant", isco_code="2411", vertical="finance",
                     labels={"en": "accountant", "bg": "счетоводител"})
    db.add(occ)
    s1 = TaxonomySkill(esco_uri="esco/s/depr", labels={"en": "depreciation", "bg": "амортизация"})
    s2 = TaxonomySkill(esco_uri="esco/s/tax", labels={"en": "tax legislation"})  # no bg -> en fallback
    db.add_all([s1, s2])
    db.flush()
    db.add_all([
        OccupationSkill(occupation_id=occ.id, skill_id=s1.id, essential=True),
        OccupationSkill(occupation_id=occ.id, skill_id=s2.id, essential=False),
    ])
    db.commit()
    return occ.id


def test_drill_down_vertical_group_occupation():
    with SessionLocal() as db:
        _seed(db)
        assert tx.verticals(db) == ["finance"]
        # top group of the vertical: 241 (its parent 24 isn't in the vertical), not the child 2411
        top = tx.groups(db, "finance")
        assert [g["isco_code"] for g in top] == ["241"]
        children = tx.groups(db, "finance", parent_code="241")
        assert [g["isco_code"] for g in children] == ["2411"]
        occs = tx.occupations(db, "2411", lang="bg")
        assert occs[0]["label"] == "счетоводител"
        assert tx.occupations(db, "2411", lang="en")[0]["label"] == "accountant"
        # ru/uk aren't in ESCO -> fall back to en
        assert tx.occupations(db, "2411", lang="ru")[0]["label"] == "accountant"


def test_occupation_skills_essential_first_with_lang_fallback():
    with SessionLocal() as db:
        oid = _seed(db)
        sk = tx.occupation_skills(db, oid, lang="bg")
        assert sk[0] == {"label": "амортизация", "essential": True}      # essential first
        assert sk[1]["essential"] is False
        assert sk[1]["label"] == "tax legislation"                       # bg empty -> en fallback


def test_search_matches_either_language():
    with SessionLocal() as db:
        _seed(db)
        assert tx.search_occupations(db, "счетов")[0]["label"] == "счетоводител"
        assert tx.search_occupations(db, "account", lang="en")[0]["label"] == "accountant"
        assert tx.search_occupations(db, "") == []
