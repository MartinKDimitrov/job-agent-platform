"""Role-family compatibility (Phase 6): the candidate's intended discipline vs the posting's.

A high semantic score can still be the wrong *kind* of role. 'Data Scientist' and 'Data
Engineer' share almost all of their vocabulary (Python, SQL, pipelines, ML), so E5 rates them
close — yet they are different jobs; a QA posting surfaced to a Backend candidate is a mismatch
no keyword overlap should rescue. This is the role-family analogue of the seniority check:
a HARD drop for the clearest cross-discipline mismatch, a SOFT down-weight for adjacent families
that are related but not the same.

Conservative by construction. A family is assigned only from a SPECIFIC cue ('backend',
'data scientist', 'qa engineer') — never from a bare 'Software Engineer' / 'Developer'. When
either side names no concrete family we cannot judge and never act: the feature only bites when
the user asked for a concrete family AND the posting clearly states a different one.
"""
import re

# family -> specific cue phrases (word-boundary matched, case-insensitive). Deliberately WITHOUT
# generic 'engineer' / 'developer': a bare title stays family-less and is never judged, so the
# check can only ever fire on an explicit, self-declared discipline.
FAMILIES: dict[str, tuple[str, ...]] = {
    "backend":      ("backend", "back-end", "back end", "server-side", "server side",
                     "api engineer", "api developer",
                     # server-stack developer titles that never say the word "backend" but are
                     # unambiguously back-end work — so a "Java Developer" no longer slips through
                     # family-less and scores on bare semantic overlap for e.g. an Android profile.
                     # Deliberately phrase-anchored (…"developer"/"engineer"), never a bare
                     # language token: "java" alone would wrongly tag a "Java/Kotlin" Android role.
                     "java developer", "java engineer", "java software engineer",
                     "spring boot", ".net developer", "c# developer", "php developer",
                     "ruby on rails", "golang developer", "go developer"),
    "frontend":     ("frontend", "front-end", "front end", "ui engineer", "ui developer"),
    "fullstack":    ("fullstack", "full-stack", "full stack"),
    "android":      ("android", "mobile developer", "mobile engineer", "react native", "flutter",
                     "kotlin multiplatform", "kmp"),
    "ios":          ("ios developer", "ios engineer", "swift developer", "objective-c", "swiftui",
                     "mobile developer", "mobile engineer", "react native", "flutter",
                     "kotlin multiplatform", "kmp"),
    "data_eng":     ("data engineer", "data engineering", "etl", "analytics engineer", "big data"),
    "data_science": ("data scientist", "data science"),
    "ml":           ("machine learning", "ml engineer", "deep learning", "nlp", "ai engineer",
                     "computer vision"),
    "data_analyst": ("data analyst", "business analyst", "bi analyst", "business intelligence"),
    "devops":       ("devops", "sre", "site reliability", "platform engineer",
                     "infrastructure engineer", "cloud engineer"),
    "qa":           ("qa engineer", "qa automation", "quality assurance", "test engineer",
                     "sdet", "automation tester", "manual tester", "qa tester"),
    "security":     ("security engineer", "appsec", "infosec", "penetration test", "pentest",
                     "cyber security", "cybersecurity"),
    "pm":           ("product manager", "product owner", "project manager", "program manager",
                     "delivery manager", "scrum master"),
    "design":       ("ux designer", "ui designer", "product designer", "ux/ui", "ui/ux",
                     "graphic designer", "web designer", "ux researcher"),
    "embedded":     ("embedded", "firmware"),
    "gamedev":      ("game developer", "gameplay", "unreal engine", "unity developer"),
}

_FAMILY_RES: dict[str, re.Pattern] = {
    fam: re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(c) for c in cues) + r")(?![a-z0-9])",
                    re.I)
    for fam, cues in FAMILIES.items()
}

# Disjoint pairs that are related enough to show (soft-weight), not drop. Symmetric — stored as
# frozensets so lookup is order-free. Anything NOT listed here and disjoint is a hard mismatch.
_ADJACENT: set[frozenset] = {frozenset(p) for p in (
    ("backend", "frontend"), ("backend", "fullstack"), ("frontend", "fullstack"),
    ("backend", "devops"), ("backend", "data_eng"), ("backend", "security"),
    ("backend", "ml"), ("backend", "embedded"),
    ("frontend", "android"), ("frontend", "ios"), ("frontend", "design"),
    ("devops", "security"), ("devops", "data_eng"),
    ("data_eng", "data_science"), ("data_eng", "data_analyst"), ("data_eng", "ml"),
    ("data_science", "ml"), ("data_science", "data_analyst"),
    ("android", "gamedev"), ("android", "embedded"), ("ios", "gamedev"), ("embedded", "gamedev"),
    # note: android and ios are deliberately NOT adjacent — a pure iOS role is a hard mismatch for
    # an Android profile (different language/SDK); cross-platform titles (React Native, Flutter,
    # KMP, "Mobile Developer") carry BOTH families, so those still match either specialist.
    # A pure backend role is likewise a HARD mismatch for a mobile profile (owner: Java/backend
    # roles must not surface for an Android candidate) — an "Android + backend" title carries the
    # android family too, so the overlap check keeps it. frontend/fullstack stay adjacent (UI overlap).
)}


def families(text: str) -> frozenset:
    """Every concrete family named in the text. 'Full stack' also counts as backend+frontend,
    so a full-stack title never conflicts with either half."""
    t = (text or "").lower()
    found = {fam for fam, rx in _FAMILY_RES.items() if rx.search(t)}
    if "fullstack" in found:
        found |= {"backend", "frontend"}
    return frozenset(found)


def conflict(profile_families: frozenset, posting_families: frozenset) -> str:
    """'none' | 'soft' | 'hard'.

    - 'none': the sets overlap, or either side names no concrete family (undecidable — never act).
    - 'soft': disjoint, but some cross-pair is adjacent (Data Scientist ↔ Data Engineer).
    - 'hard': disjoint and no cross-pair is adjacent (QA ↔ Backend, PM ↔ Data Scientist).
    """
    if not profile_families or not posting_families:
        return "none"
    if profile_families & posting_families:
        return "none"
    for p in profile_families:
        for q in posting_families:
            if frozenset((p, q)) in _ADJACENT:
                return "soft"
    return "hard"


def role_family_ok(profile, title: str) -> bool:
    """Hard filter — drop only a clearly different, non-adjacent discipline (a QA posting for a
    Backend candidate, a PM role for a Data Scientist). Adjacent or undecidable families pass and
    are handled by role_family_factor / the score."""
    return conflict(families(profile.target_roles or ""), families(title)) != "hard"


def role_family_factor(profile, title: str, *, adjacent: float = 0.8) -> float:
    """Soft multiplier for an adjacent-but-different family (Data Scientist vs Data Engineer):
    related enough to show, different enough to rank below a true match. 1.0 for a same-family
    match, a hard mismatch the filter already dropped, or anything undecidable."""
    return adjacent if conflict(families(profile.target_roles or ""),
                                families(title)) == "soft" else 1.0
