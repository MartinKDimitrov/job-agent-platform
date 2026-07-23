"""i18n scaffolding: translation fallback, language resolution, switch, and localized landings."""
import re

from app.presentation.i18n import t, LANGS, _parse_accept_language
from app.presentation.translations import CATALOGS, LANG_NAMES

EXPECTED_LANGS = {"en", "bg", "ro", "de", "nl", "fr", "es", "ru", "it", "el", "hr", "pl", "uk"}


# ---- unit: translation + parsing ----
def test_translation_and_fallback():
    assert t("nav.login", "bg") == "Вход"
    assert t("nav.login", "en") == "Sign in"
    assert t("nav.login", "fr") == "Se connecter"
    assert t("nav.login", "xx") == "Sign in"        # unknown lang -> default (en)
    assert t("does.not.exist", "bg") == "does.not.exist"  # unknown key -> the key itself


def test_all_13_languages_present():
    assert set(LANGS) == EXPECTED_LANGS
    assert set(LANG_NAMES) == EXPECTED_LANGS


def test_catalog_key_parity_and_placeholders():
    """Every catalog carries the exact EN key set, and format placeholders match — a missing
    key silently falls back to English, so only this test keeps the catalogs honest."""
    en_keys = set(CATALOGS["en"])
    for code, cat in CATALOGS.items():
        assert set(cat) == en_keys, f"{code}: key set differs from en"
        for key, val in cat.items():
            assert isinstance(val, str), f"{code}:{key} is not a string"
            assert (set(re.findall(r"\{\w+\}", val))
                    == set(re.findall(r"\{\w+\}", CATALOGS["en"][key]))), \
                f"{code}:{key} placeholder mismatch"


def test_accept_language_parsing():
    assert _parse_accept_language("bg-BG,bg;q=0.9,en;q=0.8") == "bg"
    assert _parse_accept_language("en-US,en;q=0.9") == "en"
    assert _parse_accept_language("fr-FR,fr;q=0.9") == "fr"
    assert _parse_accept_language("ja-JP,ja;q=0.9") is None       # nothing supported
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


def test_german_landing_and_switcher(client):
    client.cookies.clear()
    b = client.get("/de").text
    assert '<html lang="de">' in b
    assert "Finde Jobs, die zu dir passen" in b
    assert 'hreflang="uk"' in b and 'hreflang="el"' in b   # all languages hreflang-paired
    assert "<select class='langsw'" in b                   # dropdown switcher


def test_localized_jobs_pages(client):
    client.cookies.clear()
    assert "Emplois" in client.get("/fr/jobs").text
    b = client.get("/pl/jobs/android-dev").text
    assert '<html lang="pl">' in b and "Android Developer" in b   # EN occupation name fallback


def test_lang_cookie_accepts_new_languages(client):
    r = client.get("/lang/uk", follow_redirects=False)
    assert r.status_code == 303 and r.cookies.get("lang") == "uk"
    assert ">Увійти<" in client.get("/login").text


def test_sitemap_includes_all_languages(client):
    b = client.get("/sitemap.xml").text
    assert "<loc>http://localhost:8001/</loc>" in b
    for code in sorted(EXPECTED_LANGS - {"en"}):
        assert f"<loc>http://localhost:8001/{code}</loc>" in b
    assert "<loc>http://localhost:8001/ro/jobs</loc>" in b
    assert "<loc>http://localhost:8001/it/jobs/android-dev</loc>" in b
