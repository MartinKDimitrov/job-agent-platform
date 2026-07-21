"""Requirement extraction from a pasted job description.

Rules-based and deterministic — no LLM call, so it costs nothing to run over many postings
(see LLM_COST_STRATEGY.md). It turns raw JD text into a list of ``{"text", "kind"}`` where
``kind`` is one of ``must`` / ``nice`` / ``resp``. This is deliberately a cheap first pass;
a BYOK LLM refinement can slot in later behind the exact same return shape without touching
callers. Works for any profession — it keys off the JD's own section structure, not a fixed
technology list.

Heuristics, in order of importance:
- A bulleted line is always a list item, never a section header.
- A short, unbulleted, label-like line that names a known section switches the "current"
  bucket (must / nice / resp). Whole "drop" sections (benefits, about, perks…) are skipped.
- Boilerplate lines are dropped wherever they appear.
"""
import re

# Section headers steer classification (lowercased substring match). Bilingual BG/EN because
# the target market is BG + remote EU. Kept intentionally section-like, not generic phrases
# (a phrase like "experience with X" is a requirement, not a header) — and header detection
# only runs on non-bulleted lines anyway.
_NICE_HEADERS = ("nice to have", "nice-to-have", "bonus", "would be a plus", "a plus",
                 "preferred", "desirable", "advantageous",
                 "предимство", "ще бъде предимство", "бонус")
_RESP_HEADERS = ("responsibilit", "what you'll do", "what you will do", "the role",
                 "role description", "duties", "day to day", "day-to-day",
                 "отговорности", "какво ще правиш", "задължения")
_MUST_HEADERS = ("requirement", "qualification", "must have", "must-have", "what you'll need",
                 "what you need", "who you are", "we're looking for", "we are looking for",
                 "looking for", "skills", "изисквания", "необходими", "какво очакваме",
                 "търсим", "умения")
# Whole sections that never contain a requirement — switch into "drop" and skip until the
# next recognised header.
_DROP_HEADERS = ("about us", "about the", "about our", "who we are", "benefits", "perks",
                 "what we offer", "we offer", "why join", "why work", "our mission",
                 "diversity", "compensation", "salary", "join us", "our team",
                 "за нас", "за компанията", "ползи", "защо да", "предлагаме", "нашата мисия")

# Stray boilerplate dropped even inside a kept section.
_NOISE = ("equal opportunity", "eeo", "we are an equal", "apply now", "how to apply",
          "кандидатствай", "how to apply")

_BULLET = re.compile(r"^\s*(?:[-*•·▪●○◦→–—]|\d+[.)])\s+")
# A header line is short-ish and label-like: no sentence punctuation, optional trailing colon.
_HEADERISH = re.compile(r"^[^.!?]{1,45}:?\s*$")

_MIN_LEN = 8      # shorter than this is a fragment, not a requirement
_MAX_LEN = 180    # longer than this is prose; we try to split it into sentences
_DROP = "drop"


def _match_header(line: str) -> str | None:
    """Return the bucket a header line names, or None if it isn't a recognised header."""
    low = line.lower()
    # nice/resp take priority over must ("nice to have skills" contains "skills").
    if any(h in low for h in _NICE_HEADERS):
        return "nice"
    if any(h in low for h in _RESP_HEADERS):
        return "resp"
    if any(h in low for h in _DROP_HEADERS):
        return _DROP
    if any(h in low for h in _MUST_HEADERS):
        return "must"
    return None


def _is_noise(line: str) -> bool:
    low = line.lower()
    return any(n in low for n in _NOISE)


def _clean(line: str) -> str:
    line = _BULLET.sub("", line)
    line = line.strip(" \t•·-*–—→●○◦▪")
    return re.sub(r"\s+", " ", line).strip()


def extract_requirements(text: str, cap: int = 40) -> list[dict]:
    """Return a de-duplicated list of ``{"text", "kind"}`` requirement entries, capped."""
    if not text:
        return []
    current = "must"  # bucket for content seen before any recognised header
    out: list[dict] = []
    seen: set[str] = set()

    def add(phrase: str, kind: str) -> None:
        phrase = phrase.strip()
        if not (_MIN_LEN <= len(phrase) <= _MAX_LEN):
            return
        key = phrase.lower()
        if key in seen:
            return
        seen.add(key)
        out.append({"text": phrase, "kind": kind})

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_bullet = bool(_BULLET.match(line))
        # Only unbulleted, label-like lines can be section headers.
        if not is_bullet and _HEADERISH.match(line):
            hdr = _match_header(line)
            if hdr:
                current = hdr
                continue
        if current == _DROP or _is_noise(line):
            continue
        cleaned = _clean(line)
        if len(cleaned) > _MAX_LEN:
            # Prose paragraph: keep sentence-sized pieces rather than the whole block.
            for part in re.split(r"(?<=[.;])\s+", cleaned):
                add(part, current)
                if len(out) >= cap:
                    break
        else:
            add(cleaned, current)
        if len(out) >= cap:
            break
    return out[:cap]
