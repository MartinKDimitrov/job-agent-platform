"""Hierarchical onboarding (Stage 2): drill-down endpoints + occupation_id profile creation with
years-of-practice. Taxonomy is seeded hermetically (no live ESCO API)."""
from sqlalchemy import select

from app.data.db import SessionLocal
from app.data.models import Profile, OccupationGroup, Occupation, TaxonomySkill, OccupationSkill


def _seed_occupation(db):
    db.add_all([
        OccupationGroup(isco_code="241", parent_code="24", level=3, vertical="finance",
                        labels={"en": "Finance professionals", "bg": "Финансови специалисти"}),
        OccupationGroup(isco_code="2411", parent_code="241", level=4, vertical="finance",
                        labels={"en": "Accountants", "bg": "Одитори и счетоводители"}),
    ])
    occ = Occupation(esco_uri="esco/occ/accountant", isco_code="2411", vertical="finance",
                     labels={"en": "accountant", "bg": "счетоводител"})
    db.add(occ)
    s1 = TaxonomySkill(esco_uri="esco/s/tax", labels={"en": "tax legislation", "bg": "данъчно право"})
    s2 = TaxonomySkill(esco_uri="esco/s/depr", labels={"en": "depreciation", "bg": "амортизация"})
    db.add_all([s1, s2]); db.flush()
    db.add_all([OccupationSkill(occupation_id=occ.id, skill_id=s1.id, essential=True),
                OccupationSkill(occupation_id=occ.id, skill_id=s2.id, essential=False)])
    db.commit()
    return occ.id


# ---- GET /onboarding ----
def test_onboarding_page_shows_loaded_categories(auth_client):
    client, _ = auth_client
    with SessionLocal() as db:
        _seed_occupation(db)
    body = client.get("/onboarding").text
    assert "data-v='finance'" in body                 # the loaded vertical becomes a category
    assert "Finance &amp; Accounting" in body         # its English label (HTML-escaped &)
    client.get("/lang/bg")
    assert "Финанси и счетоводство" in client.get("/onboarding").text
    client.get("/lang/en")


def test_onboarding_requires_login(client):
    client.cookies.clear()
    r = client.get("/onboarding", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


# ---- JSON drill-down endpoints ----
def test_drilldown_endpoints(auth_client):
    client, _ = auth_client
    with SessionLocal() as db:
        oid = _seed_occupation(db)
    assert client.get("/onboarding/api/subcats?vertical=finance").json()[0]["isco_code"] == "2411"
    occs = client.get("/onboarding/api/occupations?isco=2411").json()
    assert occs[0]["id"] == oid and occs[0]["label"] == "accountant"
    skills = client.get(f"/onboarding/api/skills?occupation_id={oid}").json()
    assert skills[0]["essential"] is True             # essential first
    assert {s["label"] for s in skills} == {"tax legislation", "depreciation"}
    assert client.get("/onboarding/api/search?q=account").json()[0]["id"] == oid


def test_cities_endpoint_falls_back_to_curated(auth_client):
    client, _ = auth_client               # no City rows loaded -> curated fallback
    names = [c["name"] for c in client.get("/onboarding/api/cities?country=Bulgaria&q=sof").json()]
    assert "Sofia" in names
    assert client.get("/onboarding/api/cities?country=Germany&q=ber").json()[0]["name"] == "Berlin"


# ---- POST /onboarding ----
def test_onboarding_creates_profile_with_years(auth_client):
    client, _ = auth_client
    with SessionLocal() as db:
        oid = _seed_occupation(db)
    r = client.post("/onboarding", follow_redirects=False, data={
        "occupation_id": str(oid), "skills_blob": "tax legislation 5y, depreciation",
        "extra_skills": "Excel, SAP 3y", "country": "Bulgaria", "location_pref": "Plovdiv",
        "remote_pref": "hybrid", "relocate": "1", "english_level": "C1"})
    assert r.status_code == 303 and "/profiles/" in r.headers["location"]
    with SessionLocal() as db:
        p = db.execute(select(Profile)).scalars().one()
        assert p.target_roles == "accountant"          # English label drives matching
        assert "tax legislation 5y" in p.skills and "sap 3y" in p.skills.lower()
        assert p.location_pref == "Plovdiv" and p.remote_pref == "hybrid"
        assert p.relocate is True and p.english_level == "C1"


def test_onboarding_dedupes_skills_by_name(auth_client):
    client, _ = auth_client
    with SessionLocal() as db:
        oid = _seed_occupation(db)
    client.post("/onboarding", data={"occupation_id": str(oid),
                "skills_blob": "Kotlin 5y", "extra_skills": "kotlin, Git"})
    with SessionLocal() as db:
        p = db.execute(select(Profile)).scalars().one()
        assert p.skills.lower().count("kotlin") == 1   # dedup on skill name, keeps the years one


def test_onboarding_invalid_occupation_redirects(auth_client):
    client, _ = auth_client
    r = client.post("/onboarding", data={"occupation_id": "99999", "skills_blob": "X"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/onboarding")
    with SessionLocal() as db:
        assert db.execute(select(Profile)).scalars().all() == []


def test_onboarding_post_requires_login(client):
    client.cookies.clear()
    r = client.post("/onboarding", data={"occupation_id": "1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")
