"""Language signal for scoring.

A posting written in a language the candidate can't read is a real barrier — they can't even
parse the requirements — so it should be down-weighted. This is a **soft multiplier** (like
freshness/salary), never a hard filter, and only fires when we have data on the user's languages.

First cut = signal (1) from the roadmap: the posting's OWN language vs the user's spoken
languages. English is treated as broadly readable (EU job-market lingua franca), so English
postings are never penalized. Detection is a cheap stopword heuristic — langdetect isn't a
dependency here — good enough for a soft signal. (Signals (2) country-language and (3) explicit
"fließende Deutschkenntnisse"-style requirements are follow-ups.)
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


def language_factor(user_languages: str, posting_text: str, *, unreadable: float = 0.5) -> float:
    """Soft multiplier: 1.0 normally, `unreadable` when the posting is in a non-English language
    the user doesn't read. No user-language data -> no signal (1.0). English -> always 1.0."""
    langs = user_language_codes(user_languages)
    if not langs:
        return 1.0
    plang = detect_language(posting_text)
    if plang is None or plang == "en" or plang in langs:
        return 1.0
    return unreadable
