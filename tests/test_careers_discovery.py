"""Careers-page discovery — regression cover for the German gaps that made ~1% of real DE
employers' careers pages undiscoverable (double-r 'Karriere' href, /karriere path, and
careers-on-a-subdomain like Preh/MAHLE/Woco)."""
import app.data.ats_detect as ad


def _serve(pages: dict):
    """A fake fetch_text: returns the body for an exact URL, else None (404-ish)."""
    def fake(url, *a, **k):
        return pages.get(url.rstrip("/"))
    return fake


def test_double_r_karriere_href_on_homepage(monkeypatch):
    # Homepage links to "/karriere" — the old single-r regex missed this entirely.
    pages = {
        "https://acme.de": '<a href="/karriere">Karriere</a>',
        "https://acme.de/karriere": "<h1>Karriere</h1> offene Stellen, jetzt bewerben",
    }
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.de") == "https://acme.de/karriere"


def test_karriere_path_when_homepage_has_no_link(monkeypatch):
    # No careers link on the homepage → the /karriere fallback path must be tried.
    pages = {
        "https://acme.de": "<h1>Willkommen</h1>",
        "https://acme.de/karriere": "Stellenangebote — bewerben Sie sich",
    }
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.de") == "https://acme.de/karriere"


def test_careers_on_subdomain(monkeypatch):
    # Jobs live on karriere.<domain>, nothing on the main site (the Preh/MAHLE/Woco pattern).
    pages = {
        "https://www.acme.com": "<h1>Products</h1>",
        "https://karriere.acme.com": "<h1>Karriere</h1> offene Stellen",
    }
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://www.acme.com") == "https://karriere.acme.com"


def test_english_careers_still_found(monkeypatch):
    # The existing EN behaviour must not regress.
    pages = {
        "https://acme.com": '<a href="/careers">Careers</a>',
        "https://acme.com/careers": "Open positions — apply now, jobs",
    }
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.com") == "https://acme.com/careers"


def test_nothing_found_returns_empty(monkeypatch):
    monkeypatch.setattr(ad, "fetch_text", _serve({"https://acme.com": "<h1>Shop</h1>"}))
    assert ad.find_careers_url("https://acme.com") == ""
