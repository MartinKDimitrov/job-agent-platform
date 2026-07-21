"""Cross-source dedup: company normalization (incl. Cyrillic), title similarity, ingest merge."""
from sqlalchemy import select

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
                      description="Requirements:\n- Kotlin")


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
