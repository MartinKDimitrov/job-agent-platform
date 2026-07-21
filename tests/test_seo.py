"""SEO foundation: robots.txt, sitemap.xml, indexable landing, noindex private pages."""
import xml.etree.ElementTree as ET

from app.seo import meta_tags, site_jsonld, abs_url

PRIVATE = ["/profiles", "/account", "/sources"]


def test_robots_txt(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    assert "User-agent: *" in body
    assert "Sitemap:" in body and "/sitemap.xml" in body
    for p in PRIVATE + ["/login", "/register", "/auth"]:
        assert f"Disallow: {p}" in body


def test_sitemap_xml_is_valid_and_excludes_private(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    ET.fromstring(r.text)  # raises if not well-formed XML
    assert "<loc>" in r.text
    for p in PRIVATE:
        assert p not in r.text  # private areas never appear in the sitemap


def test_landing_is_indexable_with_full_seo(client):
    client.cookies.clear()
    b = client.get("/").text
    assert 'content="index, follow"' in b            # explicitly indexable
    assert 'noindex' not in b
    assert '<meta name="description"' in b
    assert 'rel="canonical"' in b
    assert 'property="og:title"' in b
    assert 'name="twitter:card"' in b
    assert 'application/ld+json' in b
    assert '"Organization"' in b and '"WebSite"' in b


def test_dashboard_is_noindex(auth_client):
    client, _ = auth_client
    assert 'noindex' in client.get("/").text          # logged-in dashboard is private


def test_account_page_is_noindex(auth_client):
    client, _ = auth_client
    assert 'noindex' in client.get("/account").text


def test_login_page_is_noindex(client):
    # thin utility page — public but not worth indexing
    assert 'noindex' in client.get("/login").text


# ---- unit tests for the helpers ----
def test_meta_tags_noindex_toggle():
    assert 'content="noindex, nofollow"' in meta_tags("T", "D", "/x", noindex=True)
    assert 'content="index, follow"' in meta_tags("T", "D", "/x", noindex=False)


def test_meta_tags_escapes_and_canonicalises():
    out = meta_tags('A "quote" & <b>', "desc", "/path")
    assert "&quot;" in out or "&#34;" in out           # title is HTML-escaped
    assert f'href="{abs_url("/path")}"' in out          # canonical is absolute


def test_site_jsonld_shape():
    out = site_jsonld()
    assert '"@type": "Organization"' in out and '"@type": "WebSite"' in out
    assert abs_url("/") in out
