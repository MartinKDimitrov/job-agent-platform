"""On-demand search wiring: fetch -> pre-filter -> ingest -> score -> matches (adapter mocked)."""
from sqlalchemy import select

import app.data.sources.greenhouse as gh
import app.application.usecases.search as crawl
from app.domain.entities import RawPosting
from app.application.usecases.search import run_search
from app.data.db import SessionLocal
from app.data.models import User, Profile, Posting, Match
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
    monkeypatch.setattr(crawl, "FAST_SOURCES", [])     # keep tests fully offline
    monkeypatch.setattr(crawl, "EXTRA_SOURCES", [])
    monkeypatch.setattr(crawl, "PROFILE_SOURCES", [])
    monkeypatch.setattr(crawl, "GREENHOUSE_BOARDS", list(boards))


def _make_profile_row(db, email="c@test.local", **kw):
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u)
    p = Profile(user_id=u.id, name="P", target_roles=kw.get("target_roles", "Android"),
                skills=kw.get("skills", "Kotlin"), min_match=kw.get("min_match", 0))
    db.add(p); db.commit(); db.refresh(p)
    return p


# ---- unit: run_search (ingest + DB-first score) ----
def test_prefilter_keeps_only_relevant_titles(monkeypatch):
    _mock(monkeypatch)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android")
        res = run_search(db, p)
        assert res["fetched"] == 2          # both fetched
        assert res["scored"] == 1           # only the Android one passes the pre-filter
        # the shared index keeps EVERYTHING (another user may match the sales role) —
        # but only the relevant posting gets a Match for this profile
        titles = {x.title for x in db.execute(select(Posting)).scalars()}
        assert titles == {"Senior Android Engineer", "Account Executive"}
        m = db.execute(select(Match).where(Match.profile_id == p.id)).scalars().all()
        assert len(m) == 1
        assert db.get(Posting, m[0].posting_id).title == "Senior Android Engineer"


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
                      description="Requirements:\n- Kotlin experience") for i in range(100)]
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
        assert len(posts) == 2                       # both SAMPLE postings, deduped on rerun
        matches = db.execute(select(Match).where(Match.profile_id == p.id)).scalars().all()
        assert len(matches) == 1                     # and no duplicate matches either


def test_search_now_includes_remote_boards():
    # Owner report: 'everything comes from dev.bg' with a remote profile — the one-request
    # remote boards (RemoteOK, WWR) must run on every Search now, not just the daily job.
    names = [n for n, _ in crawl.FAST_SOURCES]
    assert "remoteok" in names and "wwr" in names and "dev_bg" in names
    extra = [n for n, _ in crawl.EXTRA_SOURCES]
    assert "remoteok" not in extra and "wwr" not in extra   # no double-fetch in the daily job


# ---- route: Search now (DB-first — the route never fetches) ----
def test_search_now_button_flow(auth_client, monkeypatch):
    _mock(monkeypatch)
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin, Compose", min_match=0)
    with SessionLocal() as db:                       # the scheduled ingest fills the index
        crawl.ingest_from_sources(db)
    r = client.post(f"/profiles/{pid}/search", follow_redirects=False)
    assert r.status_code == 303 and "found=" in r.headers["location"]
    assert "pool=" in r.headers["location"]
    body = client.get(f"/profiles/{pid}?pool=2&found=1").text
    assert "Search complete" in body
    assert "Senior Android Engineer" in body         # relevant match shown
    assert "Account Executive" not in body           # irrelevant: in the index, but no Match
    assert "https://x/1" in body                     # apply link present


def test_profile_sources_receive_profile_and_merge(monkeypatch):
    # Targeted sources get the PROFILE (so dev.bg search uses the user's target roles) and
    # their results merge into the batch — this fixed 'a Business Analyst sees Android offers'.
    _mock(monkeypatch, sample=[])
    seen_profiles = []

    def fake_targeted(profile):
        seen_profiles.append(profile.target_roles)
        return [RawPosting("rss", "t1", "Business Analyst", "BulBank", location="Remote",
                           url="https://dev.bg/j/ba", apply_url="https://dev.bg/j/ba",
                           description="Requirements:\n- Requirements analysis experience")]

    monkeypatch.setattr(crawl, "PROFILE_SOURCES", [("fake_targeted", fake_targeted)])
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Business Analyst",
                              skills="Requirements Analysis, SQL", min_match=0)
        res = run_search(db, p)
        assert seen_profiles == ["Business Analyst"]
        assert res["scored"] == 1
        m = db.execute(select(Match).where(Match.profile_id == p.id)).scalars().one()
        assert db.get(Posting, m.posting_id).title == "Business Analyst"


def test_targeted_results_survive_the_cap(monkeypatch):
    # 100 generically-relevant batch postings + 1 targeted hit; with limit=10 the targeted one
    # must still be scored — targeted results are prepended, never lost to the cap race.
    big = [RawPosting("ats_api", str(i), f"Android Engineer {i}", "Acme",
                      url=f"https://x/{i}", apply_url=f"https://x/{i}",
                      description="Requirements:\n- Kotlin experience") for i in range(100)]
    _mock(monkeypatch, sample=big)
    targeted_hit = RawPosting("rss", "t9", "Android Developer", "A1 Bulgaria", location="Remote",
                              url="https://dev.bg/j/a1", apply_url="https://dev.bg/j/a1",
                              description="Requirements:\n- Kotlin and Java")
    monkeypatch.setattr(crawl, "PROFILE_SOURCES", [("t", lambda profile: [targeted_hit])])
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android", min_match=0)
        run_search(db, p, limit=10)
        titles = {db.get(Posting, m.posting_id).title
                  for m in db.execute(select(Match).where(Match.profile_id == p.id)).scalars()}
        assert "Android Developer" in titles          # the targeted hit made it


def test_concurrent_search_integrity_error_is_survived(monkeypatch):
    # Two overlapping searches can collide on uq_profile_posting at commit time; the loser
    # must roll back quietly (the winner already saved the matches), never a 500.
    from sqlalchemy.exc import IntegrityError
    _mock(monkeypatch)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android", min_match=0)
        real_commit = db.commit
        calls = {"n": 0}

        def flaky_commit():
            calls["n"] += 1
            # the FINAL commit in run_search is the one that flushes pending matches — fail it
            # once, mimicking the concurrent duplicate-key collision. Ordinals: ingest(1),
            # enrich(2), retire(3), near-dup(4), unseen(5), search_db matches(6).
            if calls["n"] == 6:
                db.rollback()
                raise IntegrityError("stmt", {}, Exception("duplicate key uq_profile_posting"))
            return real_commit()

        monkeypatch.setattr(db, "commit", flaky_commit)
        res = run_search(db, p)          # must not raise
        assert res["fetched"] >= 1
        # session remains usable afterwards
        assert db.execute(select(Posting)).scalars().all() is not None


def test_search_terms_from_target_roles():
    class P:
        target_roles = "Android Developer, Team Lead, QA"
    assert crawl._profile_search_terms(P()) == ["android developer", "team lead"]  # 'QA' <4 chars
    class Empty:
        target_roles = ""
    assert crawl._profile_search_terms(Empty()) == []


def test_generic_tool_tokens_do_not_match_titles(monkeypatch):
    # Regression: the 'Git' skill was matching GitLab's "Tenant Scale: Git" job title.
    sample = [RawPosting("ats_api", "1", "Backend Engineer (C), Tenant Scale: Git", "GitLab",
                         location="Remote", url="https://x/git", apply_url="https://x/git",
                         description="Requirements:\n- Go and Linux internals")]
    _mock(monkeypatch, sample=sample)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android Developer",
                              skills="Kotlin, Android SDK, REST API, Git, Gradle")
        res = run_search(db, p)
        assert res["scored"] == 0            # git/api/sdk are too generic to signal relevance


def test_prefilter_is_exact_token_not_substring(monkeypatch):
    # 'java' must not match 'JavaScript Developer' via substring — hmm, it's a prefix token;
    # the guarantee we need: keywords match whole title tokens only.
    sample = [RawPosting("ats_api", "1", "Capital Markets Analyst", "Acme",
                         location="Remote", url="https://x/1", apply_url="https://x/1",
                         description="Requirements:\n- Excel")]
    _mock(monkeypatch, sample=sample)
    with SessionLocal() as db:
        # 'api' (even if it survived the stoplist) must not substring-match 'Capital'
        p = _make_profile_row(db, target_roles="Backend", skills="REST API")
        res = run_search(db, p)
        assert res["scored"] == 0


def test_profile_edit_clears_stale_matches(auth_client, monkeypatch):
    _mock(monkeypatch)
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin, Compose", min_match=0)
    with SessionLocal() as db:
        crawl.ingest_from_sources(db)
    client.post(f"/profiles/{pid}/search", follow_redirects=False)
    assert "Senior Android Engineer" in client.get(f"/profiles/{pid}").text
    # edit the profile (change skills) -> old matches must be cleared until the next search
    client.post(f"/profiles/{pid}/edit",
                data={"name": "Android", "target_roles": "Android", "skills": "Kotlin",
                      "english_level": "B2", "remote_pref": "remote", "min_match": "0"})
    body = client.get(f"/profiles/{pid}").text
    assert "Senior Android Engineer" not in body
    assert "No matches above threshold" in body


def test_hard_filter_drops_management_role(monkeypatch):
    # An Android EM role passes the keyword pre-filter ("android") but must be hard-filtered out.
    sample = [
        RawPosting("ats_api", "1", "Senior Android Engineer", "Acme", location="Remote",
                   url="https://x/1", apply_url="https://x/1",
                   description="Requirements:\n- Kotlin experience"),
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


def test_postings_without_must_or_nice_requirements_never_match(monkeypatch):
    # Owner rule: no extracted requirements -> scoring is blind (sem-only, capped 60%) ->
    # such postings stay out of the feed, and pre-existing matches for them get cleaned.
    sample = [RawPosting("ats_api", "1", "Android Platform Engineer", "Acme", location="Remote",
                         url="https://x/blind", apply_url="https://x/blind",
                         description="The role:\nYou will maintain our Android platform.")]
    _mock(monkeypatch, sample=sample)
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android", min_match=0)
        res = run_search(db, p)
        assert res["matched"] == 0
        post = db.execute(select(Posting)).scalars().one()
        db.add(Match(profile_id=p.id, posting_id=post.id, score=60))   # pre-rule stale match
        db.commit()
        crawl.search_db(db, p)
        assert db.execute(select(Match).where(Match.profile_id == p.id)).first() is None
