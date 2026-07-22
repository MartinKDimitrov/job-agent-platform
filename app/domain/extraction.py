"""Requirement extraction from a pasted job description.

Rules-based and deterministic — no LLM call, so it costs nothing to run over many postings
(see LLM_COST_STRATEGY.md). It turns raw JD text into a list of ``{"text", "kind"}`` where
``kind`` is one of ``must`` / ``nice`` / ``resp`` / ``soft``. This is deliberately a cheap first pass;
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
                 "preferred", "desirable", "advantage",
                 "предимство", "ще бъде предимство", "бонус")
_RESP_HEADERS = ("responsibilit", "what you'll do", "what you will do", "the role",
                 "role description", "duties", "day to day", "day-to-day",
                 "the impact you", "your impact", "you'll be", "you will be",
                 "daily routine",
                 "отговорности", "какво ще правиш", "задължения")
_MUST_HEADERS = ("requirement", "qualification", "must have", "must-have", "what you'll need",
                 "what you need", "what you'll bring", "what you bring", "your background",
                 "who you are", "we're looking for", "we are looking for",
                 "looking for", "you'll need", "you will need", "to thrive",
                 "the ideal candidate", "the perfect candidate", "if you have",
                 "skills", "изисквания", "необходими", "какво очакваме",
                 "търсим", "умения")
# Whole sections that never contain a requirement — switch into "drop" and skip until the
# next recognised header.
_DROP_HEADERS = ("about us", "about the", "about our", "who we are", "benefits", "perks",
                 "what we offer", "we offer", "our offer", "offer you", "the company offers",
                 "why join",
                 "why work", "our mission", "diversity", "compensation", "salary", "join us",
                 "our team", "interview process", "hiring process", "application process",
                 "what's in it for you", "why you'll love", "what you get", "you will get",
                 "tip from us", "goodies", "wellbeing", "health &", "growth &",
                 "purpose & culture", "our culture", "time-off perks",
                 "за нас", "за компанията", "ползи", "защо да", "предлагаме", "нашата мисия",
                 "ние предлагаме", "ще получиш", "придобивки",
                 "процес на интервю", "процес на подбор")

# Stray boilerplate dropped even inside a kept section (real-world lines: trademark footers,
# marketing stats, EEO statements).
_NOISE = ("equal opportunity", "eeo", "we are an equal", "apply now", "how to apply",
          "registered trademark", "under license", "claim based on", "registered users",
          "fortune 100", "fortune 500", "кандидатствай")

_BULLET = re.compile(r"^\s*(?:[-*•·▪●○◦→–—]|\d+[.)])\s+")
# A header line is short-ish and label-like: no sentence punctuation, optional trailing colon
# or question mark ("What are we looking for?" is a header too). 60 chars fits real headers
# like "As a Kotlin Multiplatform Developer, you'll be:" (observed on dev.bg).
_HEADERISH = re.compile(r"^[^.!?]{1,60}[:?]?\s*$")

# Salary / location-pipe lines ("📍 London / UK Remote | £85,000-£110,000 + Benefits").
_MONEY_RE = re.compile(r"[£$€]\s*\d|\d\s*(?:лв|BGN|EUR|USD|GBP)\b", re.I)
# Perk/benefit lines — they routinely appear WITHOUT a recognizable section header (observed
# live on dev.bg postings: bulleted straight after the requirements) and are never candidate
# requirements, whatever bucket they land in.
_BENEFIT_RE = re.compile(
    r"\b(annual leave|paid leave|days off|bonus days|health insurance|dental|sports? card|"
    r"multisport|coolfit|transportation card|travel allowance|company shuttle|snacks|"
    r"soft drinks|team building|office parties|chill-?out|foosball|referral program|"
    r"salary review|performance evaluation|vouchers|corporate discounts|discounts on|"
    r"newborn|birthday|first-grader|modern office|working environment|sabbatical|"
    r"unlimited mobile|goodies|psychologist|learning platform|supportive team|"
    r"tick every box|sending us your|up-to-date cv|annual bonus|"
    r"only shortlisted|approved candidates|treated (?:strictly |with strict )?confidential|"
    r"data protection legislation|"
    r"отпуск|здравна осигуровка|спортна карта|мултиспорт|ваучери|тиймбилдинг|"
    r"карта за транспорт|бонус за)\b", re.I)
# Company self-narrative ("We're on a mission...", "Our customers...", "GitLab is the/a/where...")
# plus what-the-company-gives-you sentences ("You will have the opportunity for fully remote...").
_MARKETING_RE = re.compile(
    r"^(?:we['’]?re\b|we\s+are\b|we['’]?ve\b|we\s+want\b|we\s+build\b|our\s|join\s+us\b"
    r"|you(?:['’]ll|\s+will)?\s+(?:have|get|enjoy)\b)"
    r"|^[A-Z][\w.&-]*\s+is\s+(?:the|a|an|where)\b", re.I)
# Signals that a sentence is genuinely about the candidate's qualifications — overrides the
# marketing filter ("We are looking for someone with 5+ years..." must survive). Bare "years"
# is deliberately NOT a signal ("grown a lot in the last 10 years in the UK" is narrative);
# only the "N+ years of ..." qualification shape counts.
_REQ_SIGNAL_RE = re.compile(
    r"\b(experience|proficien\w*|knowledge|familiar\w*|degree|fluen\w*|skills?|"
    r"ability|expertise|hands-on|track record|understanding|качеств|опит|познания|"
    r"умения|владеене|образование)\b|\d+\s*\+?\s*(?:years?|години)\s+(?:of|опит|в)\b", re.I)
# Overriding the marketing filter takes a STRONG qualification signal — bare "skills"/"ability"
# is not enough ("...bright people eager to develop their professional skills" is narrative,
# "We are looking for someone with 5+ years of Kotlin experience" is a requirement).
_STRONG_SIGNAL_RE = re.compile(
    r"\b(experience|proficien\w*|knowledge|degree|fluen\w*|expertise|track record|"
    r"опит|познания|владеене|образование)\b"
    r"|\d+\s*\+?\s*(?:years?|години)\s+(?:of|опит|в)\b", re.I)

# Personality / soft-skill lines ("Team player with strong communication skills...",
# "Performance-oriented mindset—you care about..."). Nobody lists these in a skills profile,
# so scoring them as gaps is noise — they become kind="soft": extracted for transparency,
# zero weight, hidden from the gaps panel (owner feedback on the A1 card).
_SOFT_RE = re.compile(
    r"\b(team player|communication skills|interpersonal|mindset|attention to detail|"
    r"self-motivat\w*|proactive|positive attitude|can-do|work ethic|fast learner|"
    r"eager to learn|passion\w*|curiosity|curious|adaptab\w*|problem[- ]solv\w*|"
    r"комуникативн\w*|екипен играч|работа в екип|лична мотивация|адаптивн\w*)\b", re.I)

# Typographic quotes/dashes -> ASCII before ANY matching. Real postings (Yettel via dev.bg)
# use U+2019 in "What's in It for you:" / "What you'll do:", which silently missed every
# apostrophe-bearing header above and dumped the whole benefits section into the must bucket.
_TYPOGRAPHY = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})

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
    line = re.sub(r"^[\W_]+", "", line)   # leading emoji/symbols ("🚀 We're on a mission...")
    return re.sub(r"\s+", " ", line).strip()


def _keep(cleaned: str, *, seen_header: bool, is_bullet: bool) -> bool:
    """Line-level boilerplate defence, tuned on real JDs (GitLab/Monzo/Stripe):
    - salary/currency lines are never requirements;
    - company self-narrative ("We're on a mission...", "X is the platform for...") is dropped
      unless the sentence carries a genuine qualification signal ("We are looking for someone
      with 5+ years..." survives);
    - before the first recognised section header (the marketing preamble), only bullets and
      signal-bearing lines are kept — bare pasted requirement lists still work, prose intros
      don't pollute the must-bucket."""
    if _MONEY_RE.search(cleaned):
        return False
    if _BENEFIT_RE.search(cleaned):
        return False
    if _MARKETING_RE.match(cleaned) and not _STRONG_SIGNAL_RE.search(cleaned):
        return False
    if not seen_header and not is_bullet and not _REQ_SIGNAL_RE.search(cleaned):
        return False
    return True


def extract_requirements(text: str, cap: int = 40) -> list[dict]:
    """Return a de-duplicated list of ``{"text", "kind"}`` requirement entries, capped."""
    if not text:
        return []
    text = text.translate(_TYPOGRAPHY)
    current = "must"  # bucket for content seen before any recognised header
    seen_header = False
    out: list[dict] = []
    seen: set[str] = set()

    def add(phrase: str, kind: str, is_bullet: bool) -> None:
        phrase = phrase.strip()
        if not (_MIN_LEN <= len(phrase) <= _MAX_LEN):
            return
        if not _keep(phrase, seen_header=seen_header, is_bullet=is_bullet):
            return
        key = phrase.lower()
        if key in seen:
            return
        seen.add(key)
        if kind in ("must", "nice") and _SOFT_RE.search(phrase):
            kind = "soft"
        out.append({"text": phrase, "kind": kind})

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_bullet = bool(_BULLET.match(line))
        # Only unbulleted, label-like lines can be section headers. A colon-terminated line is
        # label-like at any reasonable length ("Our gratitude for the job done will be eternal,
        # but we'll also offer you:" is 74 chars and MUST hit the drop headers).
        if not is_bullet and (_HEADERISH.match(line)
                              or (line.endswith(":") and len(line) <= 100)):
            hdr = _match_header(line)
            if hdr:
                current = hdr
                seen_header = True
                continue
            # An UNRECOGNISED label line ending in ':' is still a label, never a requirement
            # ("The perfect candidate meets the following:") — skip it, keep the bucket.
            if line.endswith(":"):
                continue
        if current == _DROP or _is_noise(line):
            continue
        cleaned = _clean(line)
        if len(cleaned) > _MAX_LEN:
            # Prose paragraph: keep sentence-sized pieces rather than the whole block.
            for part in re.split(r"(?<=[.;])\s+", cleaned):
                add(part, current, is_bullet)
                if len(out) >= cap:
                    break
        else:
            add(cleaned, current, is_bullet)
        if len(out) >= cap:
            break
    return out[:cap]
