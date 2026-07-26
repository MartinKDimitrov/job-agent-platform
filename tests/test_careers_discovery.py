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


# ---- multilingual discovery: every market language must resolve, not just BG/EN/DE ----

def test_french_recrutement_href(monkeypatch):
    pages = {"https://acme.fr": '<a href="/recrutement">Recrutement</a>',
             "https://acme.fr/recrutement": "Nos offres d'emploi — postuler / rejoignez-nous"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.fr") == "https://acme.fr/recrutement"


def test_french_carrieres_path_fallback(monkeypatch):
    pages = {"https://acme.fr": "<h1>Accueil</h1>",
             "https://acme.fr/carrieres": "Carrières — postulez à nos offres d'emploi"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.fr") == "https://acme.fr/carrieres"


def test_french_recrutement_subdomain(monkeypatch):
    pages = {"https://www.acme.fr": "<h1>Produits</h1>",
             "https://recrutement.acme.fr": "Recrutement — nos offres d'emploi"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://www.acme.fr") == "https://recrutement.acme.fr"


def test_italian_lavora_con_noi(monkeypatch):
    pages = {"https://acme.it": '<a href="/lavora-con-noi">Lavora con noi</a>',
             "https://acme.it/lavora-con-noi": "Lavora con noi — posizioni aperte, candidati"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.it") == "https://acme.it/lavora-con-noi"


def test_spanish_empleo(monkeypatch):
    pages = {"https://acme.es": '<a href="/empleo">Empleo</a>',
             "https://acme.es/empleo": "Trabaja con nosotros — ofertas de empleo"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.es") == "https://acme.es/empleo"


def test_dutch_werken_bij(monkeypatch):
    pages = {"https://acme.nl": '<a href="/werken-bij">Werken bij ACME</a>',
             "https://acme.nl/werken-bij": "Werken bij ACME — bekijk onze vacatures"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.nl") == "https://acme.nl/werken-bij"


def test_polish_kariera(monkeypatch):
    pages = {"https://acme.pl": '<a href="/kariera">Kariera</a>',
             "https://acme.pl/kariera": "Kariera — praca, aplikuj już dziś"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://acme.pl") == "https://acme.pl/kariera"


# ---- TLD/country gating: probe only the site's language(s) + EN, not every language ----

def test_gating_fr_tld_skips_irrelevant_languages(monkeypatch):
    tried = []

    def rec(url, *a, **k):
        tried.append(url)
        return "<h1>Accueil</h1>" if url == "https://acme.fr" else None
    monkeypatch.setattr(ad, "fetch_text", rec)
    ad.find_careers_url("https://acme.fr")                       # .fr -> FR + EN
    assert any(u.endswith("/recrutement") for u in tried)        # French paths tried
    assert not any("/karjaar" in u or "/tyopaikat" in u or "/allasok" in u for u in tried)


def test_gating_country_overrides_com_tld(monkeypatch):
    # a German employer on a .com domain: country=DE must still trigger German probing
    pages = {"https://www.mahle.com": "<h1>Home</h1>",
             "https://karriere.mahle.com": "Karriere — offene Stellen"}
    monkeypatch.setattr(ad, "fetch_text", _serve(pages))
    assert ad.find_careers_url("https://www.mahle.com", country="DE") == \
        "https://karriere.mahle.com"
