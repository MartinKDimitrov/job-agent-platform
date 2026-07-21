"""Light onboarding: taxonomy + occupation-first profile creation."""
from sqlalchemy import select

from app.domain.taxonomy import OCCUPATIONS, by_id, all_skills
from app.data.db import SessionLocal
from app.data.models import Profile
from tests.conftest import register


# ---- taxonomy ----
def test_taxonomy_shape():
    assert by_id("android-dev")["en"] == "Android Developer"
    assert by_id("nope") is None
    assert "Kotlin" in all_skills()
    for o in OCCUPATIONS:
        assert o["id"] and o["bg"] and o["en"] and o["skills"]   # every occupation is complete


# ---- GET /onboarding ----
def test_onboarding_page_lists_occupations_and_skills(auth_client):
    client, _ = auth_client
    body = client.get("/onboarding").text
    assert "Android разработчик" in body        # occupation label (BG)
    assert "Kotlin" in body                       # embedded skill (JS) / datalist
    assert "occupation" in body                   # the select

def test_onboarding_requires_login(client):
    client.cookies.clear()
    r = client.get("/onboarding", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


# ---- POST /onboarding ----
def test_onboarding_creates_profile_from_occupation(auth_client):
    client, _ = auth_client
    r = client.post("/onboarding",
                    data={"occupation": "android-dev",
                          "skills": ["Kotlin", "Jetpack Compose"],
                          "extra_skills": "Ktor, PostgreSQL"},
                    follow_redirects=False)
    assert r.status_code == 303 and "/profiles/" in r.headers["location"]
    with SessionLocal() as db:
        p = db.execute(select(Profile)).scalars().one()
        assert p.name == "Android Developer" and p.target_roles == "Android Developer"
        skills = p.skills.lower()
        for s in ["kotlin", "jetpack compose", "ktor", "postgresql"]:
            assert s in skills
        assert p.location_pref == "Bulgaria, Sofia, Varna"    # BG-primary default
        assert p.remote_pref == "remote"


def test_onboarding_dedupes_skills(auth_client):
    client, _ = auth_client
    client.post("/onboarding", data={"occupation": "android-dev",
                                     "skills": ["Kotlin"], "extra_skills": "kotlin, Git"})
    with SessionLocal() as db:
        p = db.execute(select(Profile)).scalars().one()
        assert p.skills.lower().count("kotlin") == 1          # case-insensitive de-dup


def test_onboarding_invalid_occupation_redirects(auth_client):
    client, _ = auth_client
    r = client.post("/onboarding", data={"occupation": "not-real", "skills": ["X"]},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/onboarding")
    with SessionLocal() as db:
        assert db.execute(select(Profile)).scalars().all() == []


def test_onboarding_post_requires_login(client):
    client.cookies.clear()
    r = client.post("/onboarding", data={"occupation": "android-dev"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")
