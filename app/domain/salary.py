"""Salary extraction + soft scoring signal (Phase 7).

Deliberately CONSERVATIVE: a number only counts as a salary when a currency signal sits right
next to it — free text is full of numbers (years, headcounts, "5+ years") and a wrong salary
on a card is worse than none. The value is extracted from the RAW posting text at ingest
(extraction.py drops money lines from the requirements, so this runs on the original).

The score effect is SOFT and only fires when BOTH sides state a number (owner-approved plan):
a posting paying clearly below the candidate's expectation gets a small penalty, one meeting
it gets a small boost, everything else — including currency/period we can't compare — stays
strictly neutral. Salary must never dominate skill fit.
"""
from __future__ import annotations

import re

# currency -> alias spellings as they appear in postings (matched case-insensitively;
# symbol aliases are matched adjacent to the number, word aliases on word boundaries)
_CURRENCIES: dict[str, tuple[str, ...]] = {
    "bgn": ("bgn", "лв.", "лв", "лева", "leva"),
    "eur": ("eur", "€", "euro", "евро"),
    "usd": ("usd", "$", "us dollars"),
    "gbp": ("gbp", "£"),
    "pln": ("pln", "zł"),
    "ron": ("ron", "lei"),
    "czk": ("czk", "kč"),
    "chf": ("chf",),
    "uah": ("uah", "грн"),
}
# BGN is pegged to EUR — the one cross-currency comparison we allow.
_BGN_PER_EUR = 1.95583

_CUR_ALIASES = {alias: cur for cur, aliases in _CURRENCIES.items() for alias in aliases}
_CUR_PATTERN = "|".join(sorted((re.escape(a) for a in _CUR_ALIASES), key=len, reverse=True))

# 2000 | 2 000 | 2,000 | 2.000 | 2000.50 | 2k / 2K / 2к (Cyrillic)
_NUM = r"\d{1,3}(?:[  ,.]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?\s*[kKкК]?"
# the range's upper bound may repeat the currency symbol ("€55,000 – €70,000", "$120k-$150k")
_RANGE = (rf"(?P<a>{_NUM})(?:\s*(?:-|–|—|to|до|bis|à|a|hasta)\s*"
          rf"(?:(?:{_CUR_PATTERN})\s?)?(?P<b>{_NUM}))?")

# Two patterns (re forbids reusing group names in one alternation):
# currency after the number ("2000 - 3000 EUR", "3000 лв.") and symbol before ("€3,500").
_SAL_RES = (
    re.compile(rf"{_RANGE}\s?(?P<cur>{_CUR_PATTERN})(?![a-zа-я])", re.IGNORECASE),
    re.compile(rf"(?P<cur>{_CUR_PATTERN})\s?{_RANGE}", re.IGNORECASE),
)

_YEAR_RE = re.compile(
    r"\b(per year|annually|annual|yearly|/\s*year|p\.?a\.?|годишно|на година|jährlich|"
    r"pro jahr|par an|al año|all'anno|rocznie|на рік|jaarlijks|ετησίως|godišnje|anual)\b",
    re.IGNORECASE)
_MONTH_RE = re.compile(
    r"\b(per month|monthly|/\s*month|/\s*mo|p\.?m\.?|месечно|на месец|monatlich|par mois|"
    r"al mes|al mese|miesięcznie|на місяць|maandelijks|μηνιαίως|mjesečno|lunar)\b",
    re.IGNORECASE)


def _to_number(raw: str) -> float | None:
    s = raw.strip().replace(" ", " ")
    k = s[-1:] in ("k", "K", "к", "К")
    if k:
        s = s[:-1].strip()
    s = s.replace(" ", "")
    # 2,000 / 2.000 thousands vs 2000.50 decimals: a group of exactly 3 digits after the
    # separator with nothing following is a thousands group
    s = re.sub(r"[.,](\d{3})(?=(\D|$))", r"\1", s)
    s = s.replace(",", ".")
    try:
        val = float(s)
    except ValueError:
        return None
    return val * 1000 if k else val


def _iter_salary_matches(text: str):
    for pat in _SAL_RES:
        yield from pat.finditer(text)


def parse_salary(text: str) -> dict | None:
    """Extract {'min','max','currency','period','raw'} from free text, or None.
    period is 'month' or 'year' (explicit keyword near the match, else inferred from size)."""
    if not text:
        return None
    for m in _iter_salary_matches(text):
        cur_alias = (m.group("cur") or "").lower().strip()
        currency = _CUR_ALIASES.get(cur_alias)
        if not currency:
            continue
        a = _to_number(m.group("a") or "")
        b = _to_number(m.group("b") or "") if m.group("b") else None
        if a is None:
            continue
        lo, hi = (a, b) if b is not None else (a, a)
        if hi < lo:
            lo, hi = hi, lo
        # period: explicit keyword within a small window around the match, else infer
        window = text[max(0, m.start() - 40):m.end() + 40]
        if _YEAR_RE.search(window):
            period = "year"
        elif _MONTH_RE.search(window):
            period = "month"
        else:
            period = "year" if lo >= 25000 else "month"
        # plausibility gate: reject years-as-numbers and noise
        floor = 3000 if period == "year" else 200
        if lo < floor or hi > 2_000_000:
            continue
        return {"min": lo, "max": hi, "currency": currency, "period": period,
                "raw": text[m.start():m.end()].strip()}
    return None


def _monthly_eur_equivalent(value: float, currency: str, period: str) -> float | None:
    """Normalize to a comparable unit. Only EUR/BGN convert (pegged); other currencies
    return None against a different currency — we refuse to guess exchange rates."""
    monthly = value / 12 if period == "year" else value
    if currency == "eur":
        return monthly
    if currency == "bgn":
        return monthly / _BGN_PER_EUR
    return monthly     # same-currency comparisons use the raw monthly number


def _comparable(cur_a: str, cur_b: str) -> bool:
    return cur_a == cur_b or {cur_a, cur_b} <= {"bgn", "eur"}


def posting_salary(post) -> dict | None:
    """The stored parse as a salary dict (None when the posting states nothing)."""
    if getattr(post, "salary_min", None) is None:
        return None
    return {"min": post.salary_min, "max": post.salary_max or post.salary_min,
            "currency": post.salary_currency, "period": post.salary_period or "month"}


def salary_factor(posting: dict | None, expectation: dict | None,
                  low: float = 0.85, fit: float = 1.05) -> float:
    """Soft multiplier for the match score. 1.0 (neutral) unless BOTH sides state a salary
    in comparable currencies: `low` when the posting's max is clearly (>20%) below what the
    candidate wants, `fit` when the posting's min already meets it."""
    if not posting or not expectation:
        return 1.0
    if not _comparable(posting["currency"], expectation["currency"]):
        return 1.0
    post_min = _monthly_eur_equivalent(posting["min"], posting["currency"], posting["period"])
    post_max = _monthly_eur_equivalent(posting["max"], posting["currency"], posting["period"])
    want = _monthly_eur_equivalent(expectation["min"], expectation["currency"],
                                   expectation["period"])
    if post_max is None or want is None:
        return 1.0
    if post_max < want * 0.8:
        return low
    if post_min >= want:
        return fit
    return 1.0
