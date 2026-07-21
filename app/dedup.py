"""Cross-source deduplication (agent A3): the same job fetched from two sources (dev.bg +
JobTiger + an ATS board) has different URLs, so the URL-based content_hash can't catch it.

Key = normalized company + title similarity:
- company: lowercase → Cyrillic→Latin transliteration → drop legal suffixes (ЕАД/ООД/Ltd/...)
  and country words → light phonetic squash (c→k etc., so "ПроКредит"/"ProCredit" meet).
  Both sides go through the identical pipeline — internal consistency matters more than
  linguistic correctness.
- title: exact normalized match, or token-Jaccard ≥ 0.6 within the same company
  ("Senior Android Developer" ≈ "Senior Android Engineer"; seniority tokens keep
  "Senior X" ≠ "Junior X"). Deterministic and free — no embedding cost; an embedding
  fallback can be layered on later if needed.

Kept in memory at ingest time (no schema change); persist a dedup_key column when Alembic
migrations arrive (ROADMAP step 35).
"""
import re

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y", "ю": "yu", "я": "ya",
}
# Legal-form suffixes and country fillers that vary between listings of the same employer.
_DROP_WORDS = {
    "ead", "ood", "eood", "ad", "et", "dzzd", "ltd", "llc", "inc", "gmbh", "jsc", "plc",
    "sa", "co", "corp", "corporation", "group", "holding", "bulgaria", "balgariya", "bg",
}
_PARENS_RE = re.compile(r"\([^)]*\)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _translit(s: str) -> str:
    return "".join(_CYR.get(ch, ch) for ch in s)


def _squash(s: str) -> str:
    """Light phonetic squash so Latin spellings meet transliterations (procredit/prokredit)."""
    return s.replace("ph", "f").replace("c", "k").replace("w", "v").replace("y", "i")


_DROP_SQUASHED = {_squash(w) for w in _DROP_WORDS}


def normalize_company(name: str) -> str:
    s = _PARENS_RE.sub(" ", (name or "").lower())
    s = _squash(_translit(s))
    tokens = [t for t in _TOKEN_RE.findall(s) if t not in _DROP_SQUASHED]
    return " ".join(tokens)


# Role-word synonyms collapsed so "Senior Android Developer" ≡ "Senior Android Engineer".
_TITLE_SYNONYMS = {"developer": "engineer", "dev": "engineer", "programmer": "engineer"}


def normalize_title(title: str) -> str:
    tokens = _TOKEN_RE.findall(_squash(_translit((title or "").lower())))
    return " ".join(_TITLE_SYNONYMS.get(t, t) for t in tokens)


def title_tokens(title: str) -> set[str]:
    return set(normalize_title(title).split())


def similar_titles(a: str, b: str, threshold: float = 0.6) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    jaccard = len(ta & tb) / len(ta | tb)
    return jaccard >= threshold


def is_duplicate(company_a: str, title_a: str, company_b: str, title_b: str) -> bool:
    """Same employer (normalized) and the same-or-near-identical role title."""
    ca, cb = normalize_company(company_a), normalize_company(company_b)
    if not ca or ca != cb:
        return False
    return similar_titles(title_a, title_b)
