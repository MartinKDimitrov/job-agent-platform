"""Language signal for scoring.

A posting written in a language the candidate can't read is a real barrier — they can't even
parse the requirements — so it should be down-weighted. This is a **soft multiplier** (like
freshness/salary), never a hard filter, and only fires when we have data on the user's languages.

Three roadmap signals, strongest first:
  (3) EXPLICIT requirement — the posting demands a language ("fließende Deutschkenntnisse",
      "italiano fluente", "C1 German") the user doesn't have -> strong down-weight.
  (1) POSTING language — written in a non-English language the user can't read -> strong.
  (2) COUNTRY language — posting readable (English), but the country's everyday language is one
      the user doesn't speak -> mild (many international firms work in English).
Soft multiplier, never a hard filter; only fires when Profile.languages is set. English is
treated as broadly readable. Detection is a cheap stopword/keyword heuristic — langdetect isn't
a dependency here — good enough for a soft signal.
"""
from __future__ import annotations

import re
from collections import Counter

# Distinctive high-frequency function words per language. Overlap (e.g. "de" in nl/fr/es) is
# fine — detection takes the best-scoring language with a margin, not a single word.
_STOPWORDS = {
    "en": {"the", "and", "to", "of", "for", "with", "you", "are", "we", "our", "is", "in",
           "on", "as", "your", "will", "have", "this"},
    "de": {"und", "der", "die", "das", "mit", "für", "sie", "wir", "ein", "eine", "ist",
           "nicht", "von", "zu", "den", "im", "auf", "sind", "werden"},
    "fr": {"le", "la", "les", "et", "des", "pour", "avec", "vous", "nous", "une", "est",
           "dans", "du", "au", "sur", "que", "votre", "nos"},
    "it": {"il", "la", "le", "di", "per", "con", "una", "che", "nel", "dei", "delle", "sono",
           "gli", "alla", "come", "nostro"},
    "es": {"el", "la", "los", "las", "de", "para", "con", "una", "que", "en", "del", "por",
           "como", "nuestro", "trabajo"},
    "nl": {"het", "een", "en", "van", "voor", "met", "wij", "je", "niet", "op", "aan", "zijn",
           "onze", "jij", "wordt"},
    "pl": {"na", "do", "jest", "nie", "dla", "oraz", "się", "że", "przez", "lub", "których",
           "pracy", "naszego"},
}
_WORD_RE = re.compile(r"[a-zà-öø-ÿ]+", re.I)
_CYRILLIC_RE = re.compile(r"[а-яё]", re.I)

# Free-text language names -> ISO code (EN + native + Bulgarian names).
_LANG_NAMES = {
    "english": "en", "английски": "en", "angliyski": "en",
    "german": "de", "deutsch": "de", "немски": "de",
    "french": "fr", "francais": "fr", "français": "fr", "френски": "fr",
    "italian": "it", "italiano": "it", "италиански": "it",
    "spanish": "es", "espanol": "es", "español": "es", "испански": "es",
    "dutch": "nl", "nederlands": "nl", "нидерландски": "nl", "холандски": "nl",
    "polish": "pl", "polski": "pl", "полски": "pl",
    "bulgarian": "bg", "български": "bg", "balgarski": "bg", "bulgarski": "bg",
}


def detect_language(text: str) -> str | None:
    """Best-guess ISO code for `text`, or None when too short / ambiguous to judge."""
    t = (text or "").lower()
    if not t.strip():
        return None
    if len(_CYRILLIC_RE.findall(t)) >= 8:          # Cyrillic script -> Bulgarian (our only such market)
        return "bg"
    toks = _WORD_RE.findall(t)
    if len(toks) < 12:
        return None                                # too short to be confident
    counts = Counter(toks)
    scores = {lang: sum(counts[w] for w in words) for lang, words in _STOPWORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if top < 3 or top <= second:                   # need signal AND a clear margin
        return None
    return best


def user_language_codes(languages: str) -> set[str]:
    """ISO codes the user reads, parsed from the free-text Profile.languages field."""
    s = (languages or "").lower()
    return {code for name, code in _LANG_NAMES.items() if name in s}


# --- signal (2): the country's everyday language, from the location string --------------------
# Country / major-city keywords -> local language code. English-speaking places map to "en"
# (no penalty). Heuristic — the location field is free text (e.g. "Berlin, Germany", "София").
_COUNTRY_LANG = {
    "de": ("germany", "deutschland", "berlin", "münchen", "munich", "hamburg", "frankfurt",
           "köln", "cologne", "stuttgart", "düsseldorf", "austria", "österreich", "wien",
           "vienna", "switzerland", "zürich", "zurich"),
    "fr": ("france", "paris", "lyon", "marseille", "toulouse", "bordeaux", "nantes", "lille"),
    "it": ("italy", "italia", "rome", "roma", "milan", "milano", "turin", "torino", "naples"),
    "es": ("spain", "españa", "espana", "madrid", "barcelona", "valencia", "sevilla", "málaga"),
    "nl": ("netherlands", "nederland", "amsterdam", "rotterdam", "utrecht", "eindhoven", "hague"),
    "pl": ("poland", "polska", "warsaw", "warszawa", "kraków", "krakow", "wrocław", "wroclaw"),
    "bg": ("bulgaria", "българия", "sofia", "софия", "plovdiv", "пловдив", "varna", "варна"),
    "en": ("united kingdom", "england", "london", "manchester", "ireland", "dublin", "scotland",
           "remote", "anywhere", "worldwide"),
}


def country_language(location: str) -> str | None:
    """Local everyday language for a posting's location string, or None if unrecognized."""
    t = (location or "").lower()
    if not t.strip():
        return None
    for code, keys in _COUNTRY_LANG.items():
        if any(k in t for k in keys):
            return code
    return None


# --- signal (3): an explicit language requirement in the posting -------------------------------
_LANG_TOKEN = {
    "de": r"deutsch\w*|german|немски",
    "fr": r"fran[cç]ais|french|френски",
    "it": r"italian[oa]?|italiano|италиански",
    "es": r"espa[nñ]ol\w*|spanish|испански",
    "nl": r"nederlands|dutch|нидерландски|холандски",
    "pl": r"pol(?:ski|ish)|полски",
    "bg": r"b[aъ]lgar\w*|bulgarian|български",
}
_FLUENCY = (r"fluent|fluency|native|proficien\w+|mother\s*tongue|muttersprache|flie[sß]end\w*|"
            r"courant|corrente|kenntnisse|sprachkenntnisse|\bc1\b|\bc2\b|\bb2\b|required|"
            r"mandatory|essential|владеене|свободно|отличен")


def required_languages(text: str) -> set[str]:
    """Languages the posting EXPLICITLY requires (a language name within ~50 chars of a fluency/
    requirement indicator, either order). Heuristic — some noise is fine for a soft signal."""
    t = (text or "").lower()
    out = set()
    for code, names in _LANG_TOKEN.items():
        pat = rf"(?:{names}).{{0,50}}?(?:{_FLUENCY})|(?:{_FLUENCY}).{{0,50}}?(?:{names})"
        if re.search(pat, t):
            out.add(code)
    return out


def language_factor(user_languages: str, posting_text: str, location: str = "", *,
                    unreadable: float = 0.5, foreign_country: float = 0.9) -> float:
    """Soft multiplier combining the three signals (strongest wins). 1.0 = no barrier. No
    user-language data -> 1.0. English postings are never penalized on readability."""
    langs = user_language_codes(user_languages)
    if not langs:
        return 1.0
    # (3) explicit requirement the user meets none of -> strong barrier
    req = required_languages(posting_text)
    if req and not (req & langs):
        return unreadable
    # (1) can they even read the posting text?
    plang = detect_language(posting_text)
    if plang and plang != "en" and plang not in langs:
        return unreadable
    # (2) posting readable, but the country's everyday language is foreign -> mild
    clang = country_language(location)
    if clang and clang != "en" and clang not in langs:
        return foreign_country
    return 1.0
