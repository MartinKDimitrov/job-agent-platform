"""Public profession pages (SEO traffic engine): indexable, hreflang-paired EN/BG, live counts,
title+company samples only — never full postings or apply links publicly."""
from app.data.db import SessionLocal
from app.data.models import Posting


def _seed_posting(title="Senior Android Engineer", company="Acme",
                  description="Secret internal JD text with requirements"):
    with SessionLocal() as db:
        db.add(Posting(title=title, company=company, description=description,
                       apply_url="https://ats.example/apply/1", content_hash=title[:24]))
        db.commit()


def test_jobs_index_is_public_and_lists_occupations(client):
    r = client.get("/jobs")
    assert r.status_code == 200
    assert 'content="index, follow"' in r.text
    assert "Android Developer" in r.text and "/jobs/android-dev" in r.text


def test_profession_page_en(client):
    _seed_posting()
    b = client.get("/jobs/android-dev").text
    assert 'content="index, follow"' in b               # indexable
    assert "Android Developer jobs" in b                # localized H1
    assert ">1</b>" in b                                # live count
    assert "Senior Android Engineer" in b               # sample title
    assert "Acme" in b                                  # sample company
    assert "Kotlin" in b                                # typical skills from the taxonomy
    assert 'hreflang="bg"' in b and 'hreflang="x-default"' in b
    assert "/register" in b                             # CTA


def test_profession_page_bg(client):
    b = client.get("/bg/jobs/android-dev").text
    assert '<html lang="bg">' in b
    assert "Работа като Android разработчик" in b
    assert 'content="index, follow"' in b
    assert 'hreflang="en"' in b


def test_public_page_never_leaks_posting_internals(client):
    _seed_posting(description="Secret internal JD text with requirements")
    b = client.get("/jobs/android-dev").text
    assert "Secret internal JD" not in b                # descriptions stay private
    assert "ats.example" not in b                       # apply links stay behind registration


def test_unknown_occupation_not_indexable(client):
    b = client.get("/jobs/space-wizard").text
    assert "Not found" in b and "noindex" in b


def test_sitemap_and_robots_cover_profession_pages(client):
    sm = client.get("/sitemap.xml").text
    assert "/jobs/android-dev</loc>" in sm
    assert "/bg/jobs/android-dev</loc>" in sm
    robots = client.get("/robots.txt").text
    assert "Disallow: /jobs" not in robots              # public — crawling allowed


def test_generic_role_word_does_not_match_everything(client):
    # "QA Engineer" must not count a "Backend Engineer" posting via the generic word "engineer"
    _seed_posting(title="Backend Engineer", company="Globex")
    b = client.get("/jobs/qa-manual").text
    assert ">0</b>" in b