"""Phase 7: salary extraction from postings + the soft score signal."""
from sqlalchemy import select

import app.application.usecases.search as crawl
from app.core.config import settings
from app.data.db import SessionLocal
from app.data.ingest import ingest
from app.data.models import Posting
from app.domain.entities import RawPosting
from app.domain.salary import parse_salary, posting_salary, salary_factor
from tests.test_crawl import _make_profile_row


# ---- parser ----
def test_parses_eur_monthly_range():
    s = parse_salary("Salary: 2000 - 3000 EUR per month, fully remote")
    assert s == {"min": 2000.0, "max": 3000.0, "currency": "eur", "period": "month",
                 "raw": "2000 - 3000 EUR"}


def test_parses_bgn_and_cyrillic():
    s = parse_salary("Заплата до 3500 лв. бруто месечно")
    assert s["currency"] == "bgn" and s["max"] == 3500.0 and s["period"] == "month"


def test_parses_symbol_before_with_k_and_annual():
    s = parse_salary("Compensation: $120k - $150k per year")
    assert s == {"min": 120000.0, "max": 150000.0, "currency": "usd", "period": "year",
                 "raw": "$120k - $150k"}


def test_period_inferred_from_size():
    assert parse_salary("Pay: 60,000 EUR (gross)")["period"] == "year"
    assert parse_salary("Pay: 4 500 EUR")["period"] == "month"


def test_numbers_without_currency_are_not_salaries():
    assert parse_salary("Founded in 2019; 5+ years of Java; apply by 15.09.2025") is None
    assert parse_salary("We have 2024 employees in 12 offices") is None


def test_implausible_values_rejected():
    assert parse_salary("Pay a 5 EUR application fee") is None       # below monthly floor


# ---- soft factor ----
_WANT = {"min": 3000.0, "max": 3000.0, "currency": "eur", "period": "month"}


def test_factor_neutral_without_both_sides():
    assert salary_factor(None, _WANT) == 1.0
    assert salary_factor(_WANT, None) == 1.0


def test_factor_low_and_fit():
    low = {"min": 1500.0, "max": 2000.0, "currency": "eur", "period": "month"}
    fit = {"min": 3200.0, "max": 4000.0, "currency": "eur", "period": "month"}
    between = {"min": 2500.0, "max": 3500.0, "currency": "eur", "period": "month"}
    assert salary_factor(low, _WANT) == 0.85
    assert salary_factor(fit, _WANT) == 1.05
    assert salary_factor(between, _WANT) == 1.0     # overlaps the wish — no penalty, no boost


def test_factor_bgn_eur_pegged_and_annual_normalized():
    # 6500-8000 BGN/month ≈ 3300-4100 EUR/month — meets a 3000 EUR wish
    fit_bgn = {"min": 6500.0, "max": 8000.0, "currency": "bgn", "period": "month"}
    assert salary_factor(fit_bgn, _WANT) == 1.05
    # 60k EUR/year = 5000/month — also a fit
    fit_year = {"min": 60000.0, "max": 70000.0, "currency": "eur", "period": "year"}
    assert salary_factor(fit_year, _WANT) == 1.05


def test_factor_currency_mismatch_is_neutral():
    usd = {"min": 1000.0, "max": 1200.0, "currency": "usd", "period": "month"}
    assert salary_factor(usd, _WANT) == 1.0         # no exchange-rate guessing


# ---- ingest + scoring integration ----
def _raw(title="Android Developer", desc="", chash_url="https://x/sal1", company="Acme"):
    return RawPosting(source_kind="ats_api", external_id=chash_url, title=title,
                      company=company, url=chash_url, apply_url=chash_url,
                      location="Remote", description=desc)


def test_ingest_stores_parsed_salary():
    with SessionLocal() as db:
        ingest(db, [_raw(desc="Requirements:\n- Kotlin\nSalary: 2500 - 3000 EUR per month")])
        p = db.execute(select(Posting)).scalars().first()
        assert p.salary_min == 2500.0 and p.salary_max == 3000.0
        assert p.salary_currency == "eur" and p.salary_period == "month"
        assert p.salary_raw == "2500 - 3000 EUR"
        assert posting_salary(p) == {"min": 2500.0, "max": 3000.0,
                                     "currency": "eur", "period": "month"}


def test_salary_signal_moves_the_score(monkeypatch):
    desc_low = "Requirements:\n- Kotlin and Compose\nSalary: 800 - 1000 EUR per month"
    desc_none = "Requirements:\n- Kotlin and Compose"
    with SessionLocal() as db:
        ingest(db, [_raw(desc=desc_low, chash_url="https://x/low"),
                    _raw(title="Android Engineer", desc=desc_none,
                         chash_url="https://x/none", company="Beta Ltd")])
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin, Compose")
        p.salary_expectation = "3000 EUR"
        db.commit()
        crawl.search_db(db, p)
        rows = {post.title: m.score for m, post in db.execute(
            select(crawl.Match, Posting).join(Posting,
                                              crawl.Match.posting_id == Posting.id)).all()}
        # identical requirements — the underpaying posting must score strictly lower
        assert rows["Android Developer"] < rows["Android Engineer"]


def test_no_expectation_means_neutral(monkeypatch):
    desc_low = "Requirements:\n- Kotlin and Compose\nSalary: 800 - 1000 EUR per month"
    with SessionLocal() as db:
        ingest(db, [_raw(desc=desc_low, chash_url="https://x/low2")])
        p = _make_profile_row(db, target_roles="Android", skills="Kotlin, Compose")
        assert not p.salary_expectation
        crawl.search_db(db, p)
        m = db.execute(select(crawl.Match)).scalars().first()
        baseline = m.score
        p.salary_expectation = "3000 EUR"
        db.commit()
        crawl.search_db(db, p)
        db.refresh(m)
        assert m.score < baseline                   # the signal only fires with both sides
