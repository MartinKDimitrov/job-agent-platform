"""i18n scaffolding: translation fallback, language resolution, switch, and localized landings."""
from app.presentation.i18n import t, _parse_accept_language


# ---- unit: translation + parsing ----
def test_translation_and_fallback():
    assert t("nav.login", "bg") == "Вход"
    assert t("nav.login", "en") == "Sign in"
    assert t("nav.login", "fr") == "Sign in"        # unknown lang -> default (en)
    assert t("does.not.exist", "bg") == "does.not.exist"  # unknown key -> the key itself


def test_accept_language_parsing():
    assert _parse_accept_language("bg-BG,bg;q=0.9,en;q=0.8") == "bg"
    assert _parse_accept_language("en-US,en;q=0.9") == "en"
    assert _parse_accept_language("fr-FR,fr;q=0.9") is None       # nothing supported
    assert _parse_accept_language("en;q=0.5,bg;q=0.9") == "bg"    # q-weight wins
    assert _parse_accept_language("") is None


# ---- language resolution via requests ----
def test_login_default_language_is_english(client):
    client.cookies.clear()
    assert ">Login<" in client.get("/login").text


def test_login_respects_accept_language(client):
    client.cookies.clear()
    body = client.get("/login", headers={"Accept-Language": "bg-BG,bg;q=0.9"}).text
    assert ">Вход<" in body


def test_lang_cookie_overrides_and_is_set(client):
    r = client.get("/lang/bg", follow_redirects=False)
    assert r.status_code == 303 and r.cookies.get("lang") == "bg"
    # subsequent request in BG (cookie now in the jar)
    assert ">Вход<" in client.get("/login").text


def test_invalid_lang_code_ignored(client):
    r = client.get("/lang/zz", follow_redirects=False)
    assert "lang" not in r.cookies                    # unsupported code not stored


# ---- public landings + hreflang ----
def test_english_landing_has_hreflang_and_lang(client):
    client.cookies.clear()
    b = client.get("/").text
    assert '<html lang="en">' in b
    assert 'hreflang="en"' in b and 'hreflang="bg"' in b and 'hreflang="x-default"' in b
    assert "Find jobs that match you" in b


def test_bulgarian_landing(client):
    client.cookies.clear()
    b = client.get("/bg").text
    assert '<html lang="bg">' in b
    assert "Намери работа" in b
    assert 'content="index, follow"' in b             # public/indexable
    assert 'hreflang="bg"' in b


def test_sitemap_includes_both_languages(client):
    b = client.get("/sitemap.xml").text
    assert "<loc>http://localhost:8001/</loc>" in b
    assert "<loc>http://localhost:8001/bg</loc>" in b
