"""Lightweight i18n: translation catalogs + language resolution.

No gettext/babel dependency — plain dicts keep it cheap and modular (see LLM/cost ethos).
English is the default and the fallback; the catalogs live in app/presentation/translations/
(one module per language — 13 languages for the BG + remote-EU market). Public pages use
language-prefixed URLs (/ vs /{lang}) so hreflang works; logged-in screens resolve via the
`lang` cookie (the header switcher) and Accept-Language.
"""
from fastapi import Request

from .translations import CATALOGS, LANG_NAMES

TRANSLATIONS = CATALOGS                    # back-compat alias
LANGS = list(CATALOGS.keys())              # order = switcher order (en first, bg second)
DEFAULT_LANG = "en"

# Cookie-based switcher targets for logged-in screens (public pages pass their own
# language-prefixed URLs instead, so hreflang and canonical URLs stay correct).
SWITCH_URLS = {code: f"/lang/{code}" for code in LANGS}


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Translate `key` into `lang`, falling back to the default language, then the key itself."""
    if lang not in LANGS:
        lang = DEFAULT_LANG
    val = TRANSLATIONS.get(lang, {}).get(key)
    if val is not None:
        return val
    return TRANSLATIONS.get(DEFAULT_LANG, {}).get(key, key)


def _parse_accept_language(header: str) -> str | None:
    """Return the first supported language from an Accept-Language header, by q-weight."""
    if not header:
        return None
    weighted = []
    for item in header.split(","):
        item = item.strip()
        if not item:
            continue
        code, _, q = item.partition(";q=")
        code = code.strip().lower().split("-")[0]
        try:
            qv = float(q) if q else 1.0
        except ValueError:
            qv = 1.0
        weighted.append((qv, code))
    for _, code in sorted(weighted, key=lambda x: x[0], reverse=True):
        if code in LANGS:
            return code
    return None


def current_lang(request: Request, explicit: str | None = None) -> str:
    """Resolve the active language: explicit (URL) → cookie → Accept-Language → default."""
    if explicit in LANGS:
        return explicit
    cookie = request.cookies.get("lang")
    if cookie in LANGS:
        return cookie
    return _parse_accept_language(request.headers.get("accept-language", "")) or DEFAULT_LANG
