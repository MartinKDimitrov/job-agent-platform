"""Lightweight i18n: a small translation catalog + language resolution.

No gettext/babel dependency — a plain dict keeps it cheap and modular (see LLM/cost ethos).
English is the default and the fallback; Bulgarian is the second language for the BG + remote-EU
market. Internal (logged-in) screens stay English-only for now — add keys here when we invest in
full localization. Public pages use language-prefixed URLs (/ vs /bg) so hreflang works.
"""
from fastapi import Request

LANGS = ["en", "bg"]
DEFAULT_LANG = "en"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.dashboard": "Dashboard", "nav.documents": "Documents", "nav.sources": "Sources",
        "nav.account": "Account",
        "nav.logout": "Logout", "nav.login": "Login", "nav.register": "Register",
        "landing.title": "Job Agent — find jobs that match your skills",
        "landing.description": ("Describe your professional skills and get open positions scored "
                                "against your profile, with a direct apply link for each match."),
        "landing.h1": "Find jobs that match you",
        "landing.sub": "Create profiles, score openings against them, and apply directly.",
        "landing.get_started": "Get started", "landing.login": "Login",
        "login.title": "Login — Job Agent", "login.heading": "Login",
        "login.email": "Email", "login.password": "Password", "login.submit": "Login",
        "login.or": "Or", "auth.google": "Sign in with Google",
        "register.title": "Register — Job Agent", "register.heading": "Register",
        "register.name": "Name", "register.email": "Email", "register.password": "Password",
        "register.submit": "Create account",
    },
    "bg": {
        "nav.dashboard": "Табло", "nav.documents": "Документи", "nav.sources": "Източници",
        "nav.account": "Профил",
        "nav.logout": "Изход", "nav.login": "Вход", "nav.register": "Регистрация",
        "landing.title": "Job Agent — работа, която пасва на уменията ти",
        "landing.description": ("Опиши професионалните си умения и получи отворени позиции, "
                                "оценени спрямо профила ти, с директен линк за кандидатстване "
                                "за всяко съвпадение."),
        "landing.h1": "Намери работа, която ти пасва",
        "landing.sub": "Създай профили, оцени обяви спрямо тях и кандидатствай директно.",
        "landing.get_started": "Започни", "landing.login": "Вход",
        "login.title": "Вход — Job Agent", "login.heading": "Вход",
        "login.email": "Имейл", "login.password": "Парола", "login.submit": "Вход",
        "login.or": "Или", "auth.google": "Влез с Google",
        "register.title": "Регистрация — Job Agent", "register.heading": "Регистрация",
        "register.name": "Име", "register.email": "Имейл", "register.password": "Парола",
        "register.submit": "Създай акаунт",
    },
}


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
