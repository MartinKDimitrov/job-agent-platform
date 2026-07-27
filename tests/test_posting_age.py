"""Age filter (owner rule): postings older than a month retire from every surface."""
from datetime import datetime, timedelta

from sqlalchemy import select

import app.application.usecases.search as crawl
from app.application.usecases.search import retire_stale_postings, search_db
from app.data.db import SessionLocal
from app.data.ingest import ingest
from app.data.models import Posting, Match
from app.domain.dedup import normalize_company
from app.domain.entities import RawPosting
from tests.conftest import make_profile
from tests.test_crawl import _make_profile_row, _mock

OLD = datetime.utcnow() - timedelta(days=100)   # past the 90-day zombie cap
FRESH = datetime.utcnow() - timedelta(days=5)


def _posting(db, title, posted_at=None, first_seen=None, chash=None):
    p = Posting(title=title, company="Acme", norm_company=normalize_company("Acme"),
                url=f"https://x/{chash or title}",
                apply_url=f"https://x/{chash or title}",
                description="Requirements:\n- Kotlin experience",
                posted_at=posted_at, content_hash=chash or title)
    db.add(p); db.commit(); db.refresh(p)
    if first_seen:
        p.first_seen = first_seen
        db.commit()
    return p


def test_ingest_stores_posted_at_and_backfills_on_reseen():
    rp = RawPosting("rss", "1", "Dev", "Acme", url="https://x/1", apply_url="https://x/1",
                    description="d", posted_at=FRESH)
    with SessionLocal() as db:
        ingest(db, [RawPosting("rss", "1", "Dev", "Acme", url="https://x/1",
                               apply_url="https://x/1", description="d")])   # no date yet
        assert db.execute(select(Posting)).scalars().one().posted_at is None
        ingest(db, [rp])                                    # source now shows the date
        assert db.execute(select(Posting)).scalars().one().posted_at is not None


def test_retire_by_source_date_and_by_first_seen():
    with SessionLocal() as db:
        _posting(db, "old-by-source", posted_at=OLD, chash="a")
        _posting(db, "old-by-first-seen", first_seen=OLD, chash="b")
        _posting(db, "fresh", posted_at=FRESH, chash="c")
        # source date WINS over first_seen: an old posting we just discovered stays out
        _posting(db, "old-but-just-seen", posted_at=OLD, chash="d")
        assert retire_stale_postings(db) == 3
        live = {p.title for p in db.execute(
            select(Posting).where(Posting.is_live.is_(True))).scalars()}
        assert live == {"fresh"}


def test_search_db_skips_retired():
    with SessionLocal() as db:
        _posting(db, "Old Android Engineer", posted_at=OLD, chash="e")
        retire_stale_postings(db)
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin")
        res = search_db(db, p)
        assert res["pool"] == 0 and res["matched"] == 0


def test_feed_hides_matches_on_retired_postings(auth_client, monkeypatch):
    _mock(monkeypatch)
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin, Compose", min_match=0)
    with SessionLocal() as db:
        crawl.ingest_from_sources(db)
    client.post(f"/profiles/{pid}/search", follow_redirects=False)
    assert "Senior Android Engineer" in client.get(f"/profiles/{pid}").text
    with SessionLocal() as db:                               # the posting ages past the cutoff
        post = db.execute(select(Posting).where(
            Posting.title == "Senior Android Engineer")).scalars().one()
        post.first_seen = OLD
        db.commit()
        retire_stale_postings(db)
    body = client.get(f"/profiles/{pid}").text
    assert "Senior Android Engineer" not in body             # match exists, but never shows
    with SessionLocal() as db:
        assert db.execute(select(Match)).first() is not None


def test_public_pages_exclude_retired(client):
    with SessionLocal() as db:
        _posting(db, "Old Android Developer", posted_at=OLD, chash="f")
        _posting(db, "Fresh Android Developer", posted_at=FRESH, chash="g")
        retire_stale_postings(db)
    body = client.get("/jobs/android-dev").text
    assert "Fresh Android Developer" in body
    assert "Old Android Developer" not in body
    assert "<b>1</b>" in body                               # the count excludes retired too


# ---- takedown detection (boards + URL probe) ----
def test_unseen_board_postings_retire_but_window_urls_are_exempt():
    from app.application.usecases.search import retire_unseen_board_postings
    from app.data.company_repo import upsert_company
    with SessionLocal() as db:
        upsert_company(db, "SumUp", ats="greenhouse", ats_slug="sumup")
        unseen = _posting(db, "Gone Role", chash="u1")
        unseen.company = "SumUp"
        unseen.url = "https://sumup.com/careers/gone"
        unseen.last_seen_at = datetime.utcnow() - timedelta(hours=72)
        fresh = _posting(db, "Live Role", chash="u2")
        fresh.company = "SumUp"
        fresh.last_seen_at = datetime.utcnow() - timedelta(hours=1)
        via_devbg = _posting(db, "dev.bg Role", chash="u3")
        via_devbg.company = "SumUp"
        via_devbg.url = "https://dev.bg/company/jobads/sumup-x/"
        via_devbg.last_seen_at = datetime.utcnow() - timedelta(hours=72)
        nonboard = _posting(db, "Other Co Role", chash="u4")   # company not in the registry
        nonboard.last_seen_at = datetime.utcnow() - timedelta(hours=72)
        db.commit()
        assert retire_unseen_board_postings(db) == 1
        live = {p.title for p in db.execute(
            select(Posting).where(Posting.is_live.is_(True))).scalars()}
        assert live == {"Live Role", "dev.bg Role", "Other Co Role"}


def test_reseen_posting_resurrects_unless_age_stale():
    with SessionLocal() as db:
        p1 = _posting(db, "Early Retired", posted_at=FRESH, chash="r1")
        p1.is_live = False
        p2 = _posting(db, "Age Retired", posted_at=OLD, chash="r2")
        p2.is_live = False
        db.commit()
        ingest(db, [RawPosting("rss", "1", "Early Retired", "Acme", url="https://x/r1",
                               apply_url="https://x/r1", description="d"),
                    RawPosting("rss", "2", "Age Retired", "Acme", url="https://x/r2",
                               apply_url="https://x/r2", description="d")])
        by_title = {p.title: p for p in db.execute(select(Posting)).scalars()}
        assert by_title["Early Retired"].is_live is True     # source shows it -> resurrect
        assert by_title["Age Retired"].is_live is False      # >1 month rule always wins
        assert by_title["Age Retired"].last_seen_at is not None


def test_url_probe_retires_on_404_only(monkeypatch):
    import app.application.usecases.search as crawl
    statuses = {"https://dev.bg/company/jobads/dead/": 404,
                "https://dev.bg/company/jobads/alive/": 200,
                "https://dev.bg/company/jobads/flaky/": None}
    import app.data.sources.http as http_mod
    monkeypatch.setattr(http_mod, "url_status", lambda url, timeout=15.0: statuses[url])
    with SessionLocal() as db:
        for slug in ("dead", "alive", "flaky"):
            p = _posting(db, f"{slug} role", chash=slug)
            p.url = f"https://dev.bg/company/jobads/{slug}/"
        jt = _posting(db, "jobtiger role", chash="jt")
        jt.url = "https://www.jobtiger.bg/obiavi-za-rabota/x"
        db.commit()
        retired = crawl.probe_taken_down_urls(db, budget=10, delay=0, sleep=lambda s: None)
        assert retired == 1
        rows = {p.title: p for p in db.execute(select(Posting)).scalars()}
        assert rows["dead role"].is_live is False
        assert rows["alive role"].is_live and rows["alive role"].last_checked_at is not None
        assert rows["flaky role"].is_live                     # no proof -> untouched
        assert rows["jobtiger role"].last_checked_at is None  # excluded (crawl delay)


def test_url_probe_budget_and_off_switch(monkeypatch):
    import app.application.usecases.search as crawl
    calls = []
    import app.data.sources.http as http_mod
    monkeypatch.setattr(http_mod, "url_status",
                        lambda url, timeout=15.0: calls.append(url) or 200)
    with SessionLocal() as db:
        for i in range(5):
            p = _posting(db, f"role {i}", chash=f"b{i}")
            p.url = f"https://dev.bg/company/jobads/{i}/"
        db.commit()
        crawl.probe_taken_down_urls(db, budget=2, delay=0, sleep=lambda s: None)
        assert len(calls) == 2                                # budget respected
        assert crawl.probe_taken_down_urls(db, budget=0) == 0  # off switch (tests default)


def test_retire_disabled_when_zero():
    with SessionLocal() as db:
        _posting(db, "ancient", posted_at=OLD, chash="h")
        assert retire_stale_postings(db, max_age_days=0) == 0


def test_search_removes_matches_that_new_filters_reject():
    # A match created BEFORE a filter existed (e.g. the geo filter) must be cleaned up by the
    # next search, not shown forever (owner saw pre-geo Monzo 'Remote (UK)' cards).
    with SessionLocal() as db:
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin")
        post = _posting(db, "Android Engineer", posted_at=FRESH, chash="ukstale")
        post.url = "https://x/uk"
        post.location = "Cardiff, London or Remote (UK)"
        db.add(Match(profile_id=p.id, posting_id=post.id, score=60))
        db.commit()
        res = crawl.search_db(db, p)
        assert res["filtered"] >= 1
        assert db.execute(select(Match).where(Match.profile_id == p.id)).first() is None


# ---- Phase 4: freshness decay + must-gate + near-dup gates ----
def test_freshness_factor_curve():
    from app.domain.scoring import freshness_factor
    assert freshness_factor(None) == 1.0
    assert freshness_factor(3) == 1.0                       # fresh window
    assert freshness_factor(14) == 1.0                      # 2-week grace, full score
    assert freshness_factor(30) == 0.90
    assert abs(freshness_factor(45) - 0.85) < 0.001         # midway 30->60
    assert freshness_factor(60) == 0.80
    assert freshness_factor(80) == 0.80                     # flat until the 90d cap


def test_score_applies_freshness_and_must_gate():
    from app.domain.scoring import score
    reqs = [{"text": "Kotlin experience", "kind": "must", "skills": ["kotlin"], "weight": 5}]
    full, _, _ = score("Android · Kotlin", "role", reqs)
    aged, _, _ = score("Android · Kotlin", "role", reqs, freshness=0.85)
    assert full == 100 and aged == 85                       # decay multiplies the final
    gated, _, _ = score("Backend · Python", "role", reqs, gate_cap=0.40)
    assert gated <= 40                                      # ★5 must missed -> hard cap
    ungated, _, _ = score("Backend · Python", "role",
                          [{"text": "Kotlin experience", "kind": "must",
                            "skills": ["kotlin"], "weight": 4}], gate_cap=0.40)
    assert ungated == 0                                     # ★4 miss: no gate, just coverage


def test_near_dup_merge_gated(monkeypatch):
    import app.application.usecases.search as crawl
    with SessionLocal() as db:
        # same job reposted across two boards (dev.bg + workable) -> merges
        a = _posting(db, "Senior Java Developer (Finance)", posted_at=FRESH, chash="nd1")
        b = _posting(db, "Senior Java Dev (Finance)", posted_at=FRESH, chash="nd2")
        # same host pair with near-identical vectors -> NEVER merges (two real openings)
        c = _posting(db, "Senior Java Developer (Insurance)", posted_at=FRESH, chash="nd3")
        # different company -> never merges
        d = _posting(db, "Senior Java Developer (Finance)", posted_at=FRESH, chash="nd4")
        a.url, b.url = "https://dev.bg/company/jobads/x/", "https://apply.workable.com/acme/j/1/"
        c.url = "https://dev.bg/company/jobads/y/"
        for p, comp, vec in ((a, "Acme", [1.0, 0.0]), (b, "Acme", [0.999, 0.02]),
                             (c, "Acme", [0.999, 0.02]), (d, "OtherCo", [1.0, 0.0])):
            p.company, p.embedding = comp, vec
        db.commit()
        merged = crawl.merge_near_duplicates(db, cosine_threshold=0.96)
        assert merged == 1                                   # only the cross-board repost
        rows = {p.content_hash: p.is_live for p in db.execute(select(Posting)).scalars()}
        assert rows["nd3"] is True                           # same host: two real openings
        assert rows["nd4"] is True                           # other company untouched
        assert [rows["nd1"], rows["nd2"]].count(False) == 1  # one of the repost pair retired


def test_onsite_only_dealbreaker():
    from app.domain.filters import passes_hard_filters
    from tests.test_filters import P
    ok, reason = passes_hard_filters(P(), "Android Developer", "Remote",
                                     "Note: this is NOT a remote position.")
    assert ok is False and reason == "location"
    ok, _ = passes_hard_filters(P(remote_pref="onsite", location_pref="Sofia"),
                                "Android Developer", "Sofia",
                                "Onsite only role in Sofia.")
    assert ok is True                                       # onsite seeker unaffected
