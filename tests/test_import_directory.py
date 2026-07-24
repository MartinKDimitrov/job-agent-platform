"""Generalized national company-directory harvester."""
import app.tools.import_directory as imp


def test_profile_urls_from_sitemap(monkeypatch):
    xml = ('<urlset><url><loc>https://www.profession.hu/cegek/schaeffler-debrecen-kft</loc></url>'
           '<url><loc>https://www.profession.hu/cegek/24-7-hungary-zrt</loc></url>'
           '<url><loc>https://www.profession.hu/allasok/x</loc></url></urlset>')  # not a company
    monkeypatch.setattr(imp, "fetch_text", lambda url: xml)
    urls = imp.profile_urls(imp.SITES["hu"])
    assert urls == ["https://www.profession.hu/cegek/schaeffler-debrecen-kft",
                    "https://www.profession.hu/cegek/24-7-hungary-zrt"]


def test_name_from_slug():
    f = imp.SITES["hu"]["name_from_slug"]
    assert f("https://www.profession.hu/cegek/schaeffler-debrecen-kft") == "Schaeffler Debrecen Kft"


def test_company_website_excludes_board_and_socials():
    html = ('<a href="https://www.profession.hu/x">board</a>'
            '<a href="https://www.linkedin.com/company/x">li</a>'
            '<a href="https://cdn.x.com/logo.png">asset</a>'
            '<a href="https://www.schaeffler.hu/hu/">site</a>')
    assert imp._company_website(html, "profession.hu") == "https://www.schaeffler.hu"


def test_company_website_none_when_only_network_links():
    html = '<a href="https://www.facebook.com/x">fb</a><a href="https://profession.hu/y">b</a>'
    assert imp._company_website(html, "profession.hu") == ""
