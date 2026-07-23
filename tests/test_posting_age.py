"""Age filter (owner rule): postings older than a month retire from every surface."""
from datetime import datetime, timedelta

from sqlalchemy import select

import app.application.usecases.search as crawl
from app.application.usecases.search import retire_stale_postings, search_db
from app.data.db import SessionLocal
from app.data.ingest import ingest
from app.data.models import Posting, Match
from app.domain.entities import RawPosting
from tests.conftest import make_profile
from tests.test_crawl import _make_profile_row, _mock

OLD = datetime.utcnow() - timedelta(days=45)
FRESH = datetime.utcnow() - timedelta(days=5)


def _posting(db, title, posted_at=None, first_seen=None, chash=None):
    p = Posting(title=title, company="Acme", url=f"https://x/{chash or title}",
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


def test_retire_disabled_when_zero():
    with SessionLocal() as db:
        _posting(db, "ancient", posted_at=OLD, chash="h")
        assert retire_stale_postings(db, max_age_days=0) == 0
