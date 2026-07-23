"""Translation catalogs — one module per language, one language per file.

Every module exports CATALOG: dict[str, str] with the SAME key set as en.py (English is the
fallback, so a missing key silently falls back — the parity test in tests/test_i18n.py keeps
the catalogs honest). Public SEO copy lives here too (pub.* keys), so adding a language is:
copy en.py, translate, add one import below and one entry in LANG_NAMES.
"""
from . import bg, de, el, en, es, fr, hr, it, nl, pl, ro, ru, uk

# Order = switcher order: English first (default/fallback), Bulgarian second (home market),
# then the EU/remote-market languages alphabetically by native name.
CATALOGS: dict[str, dict[str, str]] = {
    "en": en.CATALOG, "bg": bg.CATALOG, "de": de.CATALOG, "el": el.CATALOG,
    "es": es.CATALOG, "fr": fr.CATALOG, "hr": hr.CATALOG, "it": it.CATALOG,
    "nl": nl.CATALOG, "pl": pl.CATALOG, "ro": ro.CATALOG, "ru": ru.CATALOG,
    "uk": uk.CATALOG,
}

# Native names for the language switcher (a dropdown at 13 languages).
LANG_NAMES: dict[str, str] = {
    "en": "English", "bg": "Български", "de": "Deutsch", "el": "Ελληνικά",
    "es": "Español", "fr": "Français", "hr": "Hrvatski", "it": "Italiano",
    "nl": "Nederlands", "pl": "Polski", "ro": "Română", "ru": "Русский",
    "uk": "Українська",
}
