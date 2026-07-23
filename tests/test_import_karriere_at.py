"""karriere.at importer: sitemap slugs + profile parsing (name, jobs, own-site links)."""
import app.tools.import_karriere_at as ka

PROFILE = """<html><head>
<title>ANDRITZ - Graz | Aktuelle Infos &amp; Einblicke 2026 | karriere.at</title></head>
<body>Bei uns: 54 offene Jobs.
<a href="https://www.karriere.at/jobs/andritz">interne</a>
<a href="https://www.itstellen.at/">partner board</a>
<a href="https://www.andritz.com/careers-de">Karriereseite</a>
<a href="https://www.andritz.com/group-de">Website</a>
<a href="https://kcdn.at/logo.png">logo</a>
</body></html>"""


def test_parse_profile_extracts_name_jobs_and_links():
    info = ka.parse_profile(PROFILE)
    assert info["name"] == "ANDRITZ"
    assert info["jobs"] == 54
    assert info["careers_url"] == "https://www.andritz.com/careers-de"
    assert info["website"] == "https://www.andritz.com"


def test_network_hosts_never_count_as_company_site():
    html = ('<title>X | karriere.at</title> 3 offene Jobs '
            '<a href="https://www.jobs.at/x">n</a><a href="https://hokify.at/x">n</a>')
    info = ka.parse_profile(html)
    assert info["careers_url"] == "" and info["website"] == ""


def test_company_slugs_from_sitemap(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.karriere.at/f/andritz</loc></url>
    <url><loc>https://www.karriere.at/f/raiffeisen-ober%C3%B6sterreich</loc></url>
    <url><loc>https://www.karriere.at/x/not-a-company</loc></url>
    </urlset>"""
    monkeypatch.setattr(ka, "fetch_text", lambda url: xml)
    assert ka.company_slugs() == ["andritz", "raiffeisen-oberösterreich"]


def test_parse_profile_tolerates_garbage():
    assert ka.parse_profile("") is None
    assert ka.parse_profile("<html>no title</html>") is None
