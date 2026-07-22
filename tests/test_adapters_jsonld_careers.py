"""Generic JSON-LD careers adapter (16в): link discovery, embedded lists, robots, degradation."""
import json

import app.data.sources.jsonld_careers as jc

JOB_LD = {
    "@context": "https://schema.org", "@type": "JobPosting",
    "title": "Кредитен специалист", "datePosted": "2026-07-20",
    "hiringOrganization": {"@type": "Organization", "name": "Банка АД"},
    "jobLocation": {"@type": "Place",
                    "address": {"addressLocality": "София", "addressCountry": "България"}},
    "description": "<p>Изисквания:</p><ul><li>Опит с кредитиране</li></ul>",
    "url": "https://bank.example/careers/krediten-specialist",
}

CAREERS_HTML = """<html><body>
<a href="/careers/krediten-specialist">Кредитен специалист</a>
<a href="/careers/style.css?v=1">asset</a>
<a href="https://other-site.example/jobs/x">external</a>
<a href="/careers/krediten-specialist">duplicate</a>
</body></html>"""

JOB_HTML = ('<html><head><script type="application/ld+json">'
            + json.dumps(JOB_LD, ensure_ascii=False) + "</script></head></html>")


def _mock(monkeypatch, pages: dict, robots: str | None = ""):
    jc._robots_cache.clear()

    def fake_text(url, params=None, timeout=15.0):
        if url.endswith("/robots.txt"):
            return robots
        return pages.get(url)
    monkeypatch.setattr(jc, "fetch_text", fake_text)


def test_follows_job_links_and_parses_ld(monkeypatch):
    _mock(monkeypatch, {
        "https://bank.example/careers": CAREERS_HTML,
        "https://bank.example/careers/krediten-specialist": JOB_HTML,
    })
    posts = jc.fetch("https://bank.example/careers", company_name="Банка АД",
                     delay=0, sleep=lambda s: None)
    assert len(posts) == 1                       # deduped; asset + external skipped
    p = posts[0]
    assert p.title == "Кредитен специалист" and p.company == "Банка АД"
    assert p.location == "София, България"
    assert "Опит с кредитиране" in p.description and "<" not in p.description
    assert p.url == JOB_LD["url"] and p.posted_at is not None


def test_list_page_with_embedded_postings(monkeypatch):
    two = [dict(JOB_LD), dict(JOB_LD, title="Касиер", url="https://bank.example/careers/kasier")]
    html = ('<script type="application/ld+json">' + json.dumps(two, ensure_ascii=False)
            + "</script>")
    _mock(monkeypatch, {"https://bank.example/careers": html})
    posts = jc.fetch("https://bank.example/careers", delay=0, sleep=lambda s: None)
    assert {p.title for p in posts} == {"Кредитен специалист", "Касиер"}


def test_robots_disallow_respected(monkeypatch):
    _mock(monkeypatch, {"https://bank.example/careers": CAREERS_HTML},
          robots="User-agent: *\nDisallow: /careers")
    assert jc.fetch("https://bank.example/careers", delay=0, sleep=lambda s: None) == []


def test_unreachable_robots_means_allowed(monkeypatch):
    _mock(monkeypatch, {
        "https://bank.example/careers": CAREERS_HTML,
        "https://bank.example/careers/krediten-specialist": JOB_HTML,
    }, robots=None)
    assert len(jc.fetch("https://bank.example/careers", delay=0, sleep=lambda s: None)) == 1


def test_max_jobs_budget(monkeypatch):
    links = "".join(f'<a href="/jobs/{i}">j{i}</a>' for i in range(10))
    pages = {"https://bank.example/careers": links}
    for i in range(10):
        pages[f"https://bank.example/jobs/{i}"] = (
            '<script type="application/ld+json">'
            + json.dumps(dict(JOB_LD, title=f"Job {i}", url=f"https://bank.example/jobs/{i}"))
            + "</script>")
    _mock(monkeypatch, pages)
    posts = jc.fetch("https://bank.example/careers", max_jobs=4, delay=0, sleep=lambda s: None)
    assert len(posts) == 4


def test_spa_page_yields_nothing(monkeypatch):
    _mock(monkeypatch, {"https://spa.example/careers": "<div id='root'></div>"})
    assert jc.fetch("https://spa.example/careers", delay=0, sleep=lambda s: None) == []
