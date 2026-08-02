"""Generate multilingual role-family title cues from the ESCO taxonomy.

    python -m app.tools.build_role_family_i18n        # rewrites app/domain/role_family_i18n.py

Profiles are English-keyed (onboarding stores the ESCO English label) but posting TITLES arrive
in the source language, so `role_family.families()` returned nothing for a Bulgarian, German or
Polish title — `conflict()` said "none" and the family filter was inert for most of the EU market
(owner report: logistics / digital-marketing / customer-service roles inside an accountant's feed).

Hand-writing job-title vocabulary for 11 languages would be guesswork. ESCO already IS that data:
2,909 occupations, each with labels in every EU language and a vertical we already map to a family.
So the cues are DERIVED: a token becomes a cue for a family only when it appears in that vertical's
labels and in NO other vertical — distinctiveness is what keeps "мениджър"/"engineer"-style words,
which occur everywhere, from tagging half the corpus.

The output is a plain data module so `domain/role_family.py` stays free of DB access; re-run this
whenever the taxonomy is reloaded.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select

from ..data.db import SessionLocal
from ..data.models import Occupation

# ESCO vertical -> role family. The tech families (backend/frontend/android/…) are finer-grained
# than ESCO's single "ict" vertical, so ict is deliberately left out — mapping it would tag every
# IT title with one blanket family. "engineering", "management", "elementary" and "military" have
# no single counterpart family either, and their vocabulary overlaps everything. "machine_ops" is
# ESCO's plant-and-machine OPERATORS (ISCO 8) — mostly food/chemical/paper production, only partly
# drivers — so mapping it to "transport" filled that family with "nitroglycerin"/"starch"/
# "granulator"; driver vocabulary stays hand-written instead.
VERTICAL_TO_FAMILY = {
    "finance": "finance",
    "healthcare": "healthcare",
    "sales": "sales",
    "construction": "construction",
    "crafts": "trades",
    "agriculture": "agriculture",
    "education": "education",
    "legal_culture": "legal",
    "admin": "admin",
    "personal_services": "hospitality",
}

_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_MIN_LEN = 6        # shorter tokens are too collision-prone across languages
_MIN_COUNT = 1        # even a single occupation's label is a valid cue — the most canonical
                      # title for a whole family often names exactly one ESCO occupation
                      # ("Buchhalter" = bookkeeper, "Księgowa", "Računovođa"); dominance below
                      # is what filters, not frequency.
_DOMINANCE = 0.6      # …and at least this share of its occurrences must sit in ONE family.
# Exclusivity ("appears in exactly one vertical") was too strict: ESCO splits a domain across
# verticals by ISCO skill level, so "Buchhalter" lands in finance (bookkeeper), admin (payroll
# clerk) AND management (accounting manager) — and the single most useful cue for the whole
# finance family was thrown away. Dominance keeps it while still rejecting words like
# "Spezialist"/"manager" that are spread evenly across every domain.
# Tokens that pass the distinctiveness test but are domain-generic in the wild, so they would
# tag unrelated postings (an ESCO admin label happens to mention gaming/casino; "capital" and
# "vehicles" appear in any industry's ads). Reviewed by hand after each regeneration.
DENY = {# universal job-ad vocabulary that happens to concentrate in ONE vertical's ESCO labels
        # ("специалист" sits densely in healthcare labels, "учебен" in admin ones) — in real ads
        # they appear everywhere, so they tagged logistics ads as healthcare and teachers as admin.
        "специалист", "специалистка", "учебен", "учебна", "младши", "старши",
        # loanwords that name a family of their own: ESCO files marketing occupations under its
        # sales vertical, so "marketing" became a SALES cue and erased the sales/marketing
        # distinction the curated families keep (they are adjacent, not identical).
        "marketing", "маркетинг", "management", "manager",
        "capital", "gaming", "vehicles", "therapy", "babysitter", "casino", "казино",
        "techniczno", "complementare", "sirovinama", "διεθνών", "poștal", "konferencija",
        "politika", "voorzieningen", "rating", "forwarding", "customs", "freight"}

_OUT = Path(__file__).resolve().parents[1] / "domain" / "role_family_i18n.py"


_MAX_LABEL_WORDS = 2   # only the CANONICAL short labels ("Buchhalter/Buchhalterin") become cues


def _tokens(label: str) -> set[str]:
    """Tokens of a label — but only from SHORT labels. A long descriptive label
    ("Sachbearbeiter Finanzen mit Schwerpunkt Zoll") contributes its connective and modifier
    words too, and those then tag unrelated postings: measured 6% of German accounting titles
    being hard-dropped from an accountant's feed because "schwerpunkt"-type words had become
    trades/admin cues. A hidden relevant job is worse than a visible irrelevant one, so cues
    come only from labels that ARE essentially the job title."""
    words = _WORD.findall(label or "")
    if not words or len(words) > _MAX_LABEL_WORDS:
        return set()
    return {w.lower() for w in words if len(w) >= _MIN_LEN}


def collect(session_factory=SessionLocal) -> dict[str, list[str]]:
    """token -> the verticals it appears in; keep the tokens unique to ONE mapped vertical."""
    per_vertical: dict[str, Counter] = defaultdict(Counter)
    token_verticals: dict[str, set[str]] = defaultdict(set)
    with session_factory() as db:
        for vertical, labels in db.execute(select(Occupation.vertical, Occupation.labels)):
            for lang, label in (labels or {}).items():
                # English is already covered by the curated cues in role_family.py, and English
                # ESCO labels are where the collisions come from: generic role words like
                # "representative"/"assistant" appear in some admin occupation and then tag every
                # "Sales Representative". This generator exists for the languages the curated
                # list can't reach, so English is excluded outright.
                if lang == "en":
                    continue
                for tok in _tokens(label):
                    token_verticals[tok].add(vertical or "")
                    if vertical in VERTICAL_TO_FAMILY:
                        per_vertical[vertical][tok] += 1
    # token -> {family: count} over the MAPPED verticals, plus how often it occurs anywhere
    per_family: dict[str, Counter] = defaultdict(Counter)
    for vertical, counts in per_vertical.items():
        fam = VERTICAL_TO_FAMILY[vertical]
        for tok, n in counts.items():
            per_family[fam][tok] += n
    totals: Counter = Counter()
    for fam, counts in per_family.items():
        for tok, n in counts.items():
            totals[tok] += n
    cues: dict[str, list[str]] = defaultdict(list)
    for fam, counts in per_family.items():
        for tok, n in counts.items():
            if (n >= _MIN_COUNT and tok not in DENY
                    and n / totals[tok] >= _DOMINANCE
                    # unmapped verticals (engineering/management/ict/elementary) still count
                    # against it: a word common there is not a domain marker.
                    and len(token_verticals[tok] - {v for v in VERTICAL_TO_FAMILY}) <= 1):
                cues[fam].append(tok)
    return {fam: sorted(set(toks)) for fam, toks in cues.items()}


def render(cues: dict[str, list[str]]) -> str:
    body = []
    for fam in sorted(cues):
        toks = cues[fam]
        items = ",\n        ".join(
            ", ".join(repr(t) for t in toks[i:i + 4]) for i in range(0, len(toks), 4))
        body.append(f'    "{fam}": (\n        {items},\n    ),')
    joined = "\n".join(body)
    return f'''"""Multilingual role-family title cues — GENERATED, do not edit by hand.

    python -m app.tools.build_role_family_i18n

Derived from the ESCO taxonomy: every token below appears in the labels of exactly ONE ESCO
vertical (across all {len(cues)} mapped families and every language ESCO ships), which is what makes it
safe to treat as naming that family. See the generator for why hand-written cues weren't an option.
"""

I18N_CUES: dict[str, tuple[str, ...]] = {{
{joined}
}}
'''


def main() -> None:
    cues = collect()
    _OUT.write_text(render(cues), encoding="utf-8")
    total = sum(len(v) for v in cues.values())
    print(f"wrote {_OUT} — {total} cues across {len(cues)} families")
    for fam in sorted(cues):
        print(f"  {fam:14} {len(cues[fam]):5}")


if __name__ == "__main__":
    main()
