"""On-demand search wiring: fetch -> pre-filter -> ingest -> score -> matches (adapter mocked)."""
from sqlalchemy import select

import app.adapters.greenhouse as gh
import app.crawl as crawl
from app.adapters.base import RawPosting
from app.crawl import run_search
from app.db import SessionLocal
from app.models import User, Profile, Posting, Match
from tests.conftest import register, make_profile

SAMPLE = [
    RawPosting("ats_api", "1", "Senior Android Engineer", "Acme", location="Remote",
               url="https://x/1", apply_url="https://x/1",
               description="Requirements:\n- Kotlin and Compose\n- CI/CD pipelines"),
    RawPosting("ats_api", "2", "Account Executive", "Acme",
               url="https://x/2", apply_url="https://x/2", description="Sales role"),
]


def _mock(monkeypatch, sample=SAMPLE, boards=(("acme", "Acme"),)):
    monkeypatch.setattr(gh, "fetch", lambda token, company_name=None: list(sample))
    monkeypatch.setattr(crawl, "GREENHOUSE_BOARDS", list(boards))


def _make_profile_row(db, email="c@test.local", **kw):
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u)
    p = Profile(user_id=u.id, name="P", target_roles=kw.get("target_roles", "Android"),
                skills=kw.get("skills", "Kotlin"), min_match=kw.get("min_match", 0))
    db.add(p); db.commit(); db.refresh(p)
    return p


# ---- unit: run_search ----
def test_prefilter_keeps_only_relevant_titles(monkeypatch):
    _mock(monkeypatch)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android")
        res = run_search(db, p)
        assert res["fetched"] == 2          # both fetched
        assert res["scored"] == 1           # only the Android one passes the pre-filter
        posts = db.execute(select(Posting)).scalars().all()
        assert [x.title for x in posts] == ["Senior Android Engineer"]


def test_matches_created_and_apply_url_kept(monkeypatch):
    _mock(monkeypatch)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin, Compose", min_match=0)
        res = run_search(db, p)
        assert res["matched"] >= 1
        m = db.execute(select(Match).where(Match.profile_id == p.id)).scalars().all()
        assert len(m) == 1
        post = db.get(Posting, m[0].posting_id)
        assert post.apply_url == "https://x/1"
        assert post.requirements                     # requirements were extracted


def test_cap_limits_scored(monkeypatch):
    big = [RawPosting("ats_api", str(i), f"Android Engineer {i}", "Acme",
                      url=f"https://x/{i}", apply_url=f"https://x/{i}",
                      description="Requirements:\n- Kotlin") for i in range(100)]
    _mock(monkeypatch, sample=big)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android")
        res = run_search(db, p, limit=10)
        assert res["scored"] == 10


def test_rerun_does_not_duplicate(monkeypatch):
    _mock(monkeypatch)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android")
        run_search(db, p)
        run_search(db, p)
        posts = db.execute(select(Posting)).scalars().all()
        assert len(posts) == 1                       # deduped by content_hash


# ---- route: Search now ----
def test_search_now_button_flow(auth_client, monkeypatch):
    _mock(monkeypatch)
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin, Compose", min_match=0)
    r = client.post(f"/profiles/{pid}/search", follow_redirects=False)
    assert r.status_code == 303 and "found=" in r.headers["location"]
    body = client.get(f"/profiles/{pid}?fetched=2&new=1&found=1").text
    assert "Search complete" in body
    assert "Senior Android Engineer" in body         # relevant match shown
    assert "Account Executive" not in body           # irrelevant filtered out
    assert "https://x/1" in body                     # apply link present


def test_hard_filter_drops_management_role(monkeypatch):
    # An Android EM role passes the keyword pre-filter ("android") but must be hard-filtered out.
    sample = [
        RawPosting("ats_api", "1", "Senior Android Engineer", "Acme", location="Remote",
                   url="https://x/1", apply_url="https://x/1",
                   description="Requirements:\n- Kotlin"),
        RawPosting("ats_api", "2", "Android Engineering Manager", "Acme", location="Remote",
                   url="https://x/2", apply_url="https://x/2",
                   description="Requirements:\n- Kotlin\n- Lead a team"),
    ]
    _mock(monkeypatch, sample=sample)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android", min_match=0)
        res = run_search(db, p)
        assert res["filtered"] == 1          # the EM role dropped
        assert res["scored"] == 1            # only the IC role scored
        titles = {x.title for x in db.execute(select(Posting)).scalars().all()}
        # both are ingested (postings are shared), but only the IC role gets a Match
        matches = db.execute(select(Match).where(Match.profile_id == p.id)).scalars().all()
        matched_titles = {db.get(Posting, m.posting_id).title for m in matches}
        assert matched_titles == {"Senior Android Engineer"}


def test_cannot_search_another_users_profile(client, monkeypatch):
    _mock(monkeypatch)
    register(client, email="owner2@test.local")
    pid = make_profile(client, target_roles="Android")
    register(client, email="intruder2@test.local")
    r = client.post(f"/profiles/{pid}/search", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/")
    with SessionLocal() as db:
        assert db.execute(select(Match).where(Match.profile_id == pid)).first() is None
