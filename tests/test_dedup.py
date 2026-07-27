"""Cross-source dedup: company normalization (incl. Cyrillic), title similarity, ingest merge."""
from sqlalchemy import func, select

from app.domain.dedup import normalize_company, normalize_title, similar_titles, is_duplicate
from app.domain.entities import RawPosting
from app.data.ingest import ingest
from app.data.db import SessionLocal
from app.data.models import Posting


# ---- normalization ----
def test_company_cyrillic_meets_latin():
    assert (normalize_company("ПроКредит Банк (България) ЕАД")
            == normalize_company("ProCredit Bank"))


def test_company_legal_suffixes_dropped():
    assert normalize_company("Acme Ltd") == normalize_company("Acme") == normalize_company("ACME EOOD")
    assert normalize_company("") == ""


def test_title_synonyms_and_translit():
    assert normalize_title("Senior Android Developer") == normalize_title("Senior Android Engineer")
    assert normalize_title("Програмист") == normalize_title("programist")


# ---- similarity ----
def test_similar_titles_near_match():
    assert similar_titles("Senior Android Engineer (m/f)", "Senior Android Engineer")
    assert not similar_titles("Senior Android Engineer", "Junior Accountant")
    assert not similar_titles("", "Anything")


def test_seniority_still_distinguishes():
    # different seniority should NOT collapse: {senior,x,engineer} vs {junior,x,engineer}
    assert not similar_titles("Senior Data Engineer", "Junior Data Engineer")


def test_is_duplicate_requires_same_company():
    assert is_duplicate("Acme Ltd", "QA Engineer", "ACME", "QA Engineer")
    assert not is_duplicate("Acme", "QA Engineer", "Globex", "QA Engineer")
    assert not is_duplicate("Acme", "QA Engineer", "Acme", "Frontend Engineer")


# ---- ingest integration ----
def _rp(kind, url, title="Senior Android Engineer", company="Acme", apply_url=None):
    return RawPosting(kind, url, title, company, url=url, apply_url=apply_url or url,
                      description="Requirements:\n- Kotlin experience")


def test_cross_source_duplicate_lands_once():
    with SessionLocal() as db:
        ingest(db, [_rp("rss", "https://dev.bg/j/1")])
        res = ingest(db, [_rp("html", "https://jobtiger.bg/j/xyz",
                              title="Senior Android Developer")])   # synonym + other source
        assert res == {"added": 0, "skipped": 0, "deduped": 1}
        assert len(db.execute(select(Posting)).scalars().all()) == 1


def test_within_batch_duplicate_collapses():
    with SessionLocal() as db:
        res = ingest(db, [_rp("rss", "https://a/1"), _rp("html", "https://b/2")])
        assert res["added"] == 1 and res["deduped"] == 1


def test_content_hash_is_unique():
    """The UNIQUE constraint makes duplicate content_hash rows impossible at the DB level."""
    from sqlalchemy.exc import IntegrityError
    with SessionLocal() as db:
        db.add_all([
            Posting(title="A", company="Acme", url="https://u/1", apply_url="https://u/1",
                    description="d", content_hash="same"),
            Posting(title="B", company="Beta", url="https://u/2", apply_url="https://u/2",
                    description="d", content_hash="same")])
        try:
            db.commit()
            assert False, "expected a unique-violation on content_hash"
        except IntegrityError:
            db.rollback()


def test_ingest_race_touches_instead_of_duplicating(monkeypatch):
    """Concurrent-writer race: another worker inserts the same content_hash between our SELECT
    and INSERT. The unique constraint rejects our INSERT; ingest catches it, touches the winner,
    and never duplicates or crashes."""
    import app.data.ingest as ing
    rp = _rp("rss", "https://race/1")
    chash = rp.content_hash()
    with SessionLocal() as db:                  # the concurrent winner already committed it
        db.add(Posting(title="A", company="Zeta", url="https://race/1", apply_url="https://race/1",
                       description="d", content_hash=chash))
        db.commit()
    real, calls = ing._existing_by_hash, {"n": 0}

    def flaky(db, ch):                          # miss on the first look (race), real thereafter
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db, ch)
    monkeypatch.setattr(ing, "_existing_by_hash", flaky)
    with SessionLocal() as db:
        res = ing.ingest(db, [rp])              # SELECT misses -> INSERT -> IntegrityError -> touch
    assert res["added"] == 0 and res["skipped"] == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Posting.id)).where(Posting.content_hash == chash)) == 1


def test_ats_duplicate_upgrades_apply_url():
    with SessionLocal() as db:
        ingest(db, [_rp("html", "https://jobtiger.bg/j/1")])
        ingest(db, [_rp("ats_api", "https://boards.greenhouse.io/acme/jobs/9",
                        apply_url="https://boards.greenhouse.io/acme/jobs/9")])
        post = db.execute(select(Posting)).scalars().one()
        assert post.apply_url == "https://boards.greenhouse.io/acme/jobs/9"   # canonical won


def test_non_ats_duplicate_does_not_downgrade():
    with SessionLocal() as db:
        ingest(db, [_rp("ats_api", "https://boards.greenhouse.io/acme/jobs/9")])
        ingest(db, [_rp("rss", "https://dev.bg/j/1")])
        post = db.execute(select(Posting)).scalars().one()
        assert post.apply_url == "https://boards.greenhouse.io/acme/jobs/9"   # kept


def test_different_companies_same_title_not_deduped():
    with SessionLocal() as db:
        res = ingest(db, [_rp("rss", "https://a/1", company="Acme"),
                          _rp("rss", "https://b/2", company="Globex")])
        assert res["added"] == 2 and res["deduped"] == 0


def test_long_fields_clamped_to_column_limits():
    # Postgres rejects the whole INSERT batch on a >255-char varchar (a long Ashby
    # multi-location string killed a live ingest); SQLite doesn't enforce, so assert the clamp.
    from app.data.db import SessionLocal
    from app.data.models import Posting
    from sqlalchemy import select
    rp = RawPosting("ats_api", "long1", "T" * 600, "C" * 300, location="L" * 300,
                    url="https://x/long", apply_url="https://x/long", description="d")
    with SessionLocal() as db:
        ingest(db, [rp])
        p = db.execute(select(Posting)).scalars().one()
        assert len(p.title) == 512 and len(p.company) == 255 and len(p.location) == 255
