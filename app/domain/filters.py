"""Hard filters applied BEFORE the % score (ARCHITECTURE §5).

A posting that fails location or seniority compatibility is dropped, not shown — no amount of
semantic similarity should surface an Engineering Manager role to an Android IC, or an onsite
role in another city to a remote-only candidate. Rules-based, no LLM. The candidate's *intent*
comes from their profile (target_roles / remote_pref / location_pref), so the user controls the
filters implicitly by how they describe what they want.
"""
import re
from functools import lru_cache

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-Я0-9\+\#\.]+")

# Title cues. "lead"/"principal"/"staff" read as senior IC, not management — only real people-
# management titles go here, so e.g. "Tech Lead" is not treated as a manager role.
_MGMT = ("manager", "head of", "head, ", "director", "vice president", " vp", "vp ", "svp",
         "evp", "chief", "cto", "ceo", "cfo", "coo", "team lead", "people lead",
         "engineering lead", "supervisor", "leadership")
# Titles that contain "manager" but are individual-contributor / functional roles — NOT
# people-management. A Product/Account/Project Manager is not a mismatch for an IC candidate.
_IC_MANAGER = ("product manager", "account manager", "project manager", "program manager",
               "community manager", "product marketing manager", "customer success manager",
               "engagement manager", "social media manager", "content manager")
_JUNIOR = ("junior", "jr.", "jr ", "intern", "graduate", "entry level", "entry-level",
           "apprentice", "trainee", "working student", "стажант")
_SENIOR = ("senior", "sr.", "sr ", "staff", "principal", "lead", "expert")
_REMOTE = ("remote", "anywhere", "distributed", "work from home", "wfh", "worldwide",
           "remote-first", "дистанционно")


def _has(text: str, needles) -> bool:
    t = (text or "").lower()
    return any(n in t for n in needles)


def _tokens(s: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall((s or "").lower()) if len(tok) > 2}


def _posting_is_mgmt(title: str) -> bool:
    if _has(title, _IC_MANAGER):          # Product/Account/Project Manager etc. = IC, not people-mgmt
        return False
    return _has(title, _MGMT)


def _posting_level(title: str) -> int:
    if _has(title, _JUNIOR):
        return 0
    if _has(title, _SENIOR):
        return 2
    return 1  # mid / unspecified


def _profile_wants_mgmt(profile) -> bool:
    return _has(f"{profile.target_roles or ''} {profile.experience or ''}", _MGMT)


def _profile_level(profile) -> int:
    tr = profile.target_roles or ""
    if _has(tr, _JUNIOR):
        return 0
    if _has(tr, _SENIOR):
        return 2
    return 1


# ---- geo restrictions (owner report: a "Remote" posting actually required moving to the UK) ----
# country key -> alias phrases as they appear in postings; matched with word boundaries
# (naive substring is dangerous: "the us" would match "the usER").
_COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "bulgaria": ("bulgaria", "българия"),
    "uk": ("united kingdom", "the uk", "uk", "england", "great britain", "britain",
           "uk-based", "london"),
    "usa": ("united states", "the us", "usa", r"u\.s\.", "us-based", "us only",
            "north america", "texas", "california", "new york"),
    "canada": ("canada",),
    "germany": ("germany", "deutschland", "berlin", "münchen", "munich"),
    "france": ("france", "paris"),
    "netherlands": ("netherlands", "amsterdam"),
    "spain": ("spain",), "italy": ("italy",), "poland": ("poland",),
    "romania": ("romania",), "greece": ("greece",), "austria": ("austria",),
    "portugal": ("portugal",), "ireland": ("ireland",), "belgium": ("belgium",),
    "switzerland": ("switzerland",), "sweden": ("sweden",), "denmark": ("denmark",),
    "norway": ("norway",), "finland": ("finland",), "czechia": ("czech republic", "czechia"),
    "hungary": ("hungary",), "serbia": ("serbia",), "turkey": ("turkey", "türkiye"),
    "ukraine": ("ukraine",), "india": ("india",), "australia": ("australia",),
}
_ALIAS_RES: dict[str, re.Pattern] = {
    key: re.compile(r"\b(?:" + "|".join(a if "\\" in a else re.escape(a)
                                        for a in aliases) + r")\b", re.I)
    for key, aliases in _COUNTRY_ALIASES.items()
}
_EU_COUNTRIES = {"bulgaria", "germany", "france", "netherlands", "spain", "italy", "poland",
                 "romania", "greece", "austria", "portugal", "ireland", "belgium", "sweden",
                 "denmark", "finland", "czechia", "hungary"}
_EU_REGION_RE = re.compile(r"\b(eu|european union|europe|emea|cee|balkans?)\b", re.I)
# description phrases that turn a country mention into a REQUIREMENT (a JD merely mentioning
# "clients in the US" must not drop the posting). {c} is the country alias pattern.
_RESTRICT_TEMPLATES = (
    r"based in (?:the )?{c}", r"located in (?:the )?{c}", r"living in (?:the )?{c}",
    r"resid(?:e|ing|ent[s]?) (?:in|of) (?:the )?{c}", r"citizens? of (?:the )?{c}",
    r"eligible to work in (?:the )?{c}", r"authori[sz]ed to work in (?:the )?{c}",
    r"work permit (?:in|for) (?:the )?{c}", r"right to work in (?:the )?{c}",
    r"remote (?:in|from|within) (?:the )?{c}", r"remote \((?:the )?{c}",
    r"must be in (?:the )?{c}", r"relocat(?:e|ion) to (?:the )?{c}")
_RESTRICT_RES: dict[str, re.Pattern] = {
    key: re.compile("|".join(
        t.format(c="(?:" + "|".join(a if "\\" in a else re.escape(a) for a in aliases) + ")")
        for t in _RESTRICT_TEMPLATES), re.I)
    for key, aliases in _COUNTRY_ALIASES.items()
}
_RELOC_RE = re.compile(r"\b(relocation (?:is )?required|willing(?:ness)? to relocate|"
                       r"must relocate|require[sd]? relocation)\b", re.I)


def _profile_country(profile) -> str:
    raw = (getattr(profile, "country", "") or "bulgaria")
    for key, pat in _ALIAS_RES.items():
        if key.lower() in raw.lower() or pat.search(raw):
            return key
    return "bulgaria"


@lru_cache(maxsize=4096)
def _restricted_countries(location: str, description: str) -> frozenset[str]:
    """Countries a posting is restricted to. In the LOCATION field any country mention counts
    (that's what the field is for); in the DESCRIPTION only requirement-shaped phrases.
    Profile-independent and regex-heavy (~30 country patterns over multi-KB descriptions —
    profiled at 2.9s per search across the candidate set), so it's memoized per posting
    text: each posting pays once per process, warm searches pay nothing."""
    out: set[str] = set()
    for key in _COUNTRY_ALIASES:
        if location and _ALIAS_RES[key].search(location):
            out.add(key)
        elif description and _RESTRICT_RES[key].search(description):
            out.add(key)
    return frozenset(out)


def geo_ok(profile, location: str, description: str = "") -> bool:
    """False when the posting is tied to a country the candidate doesn't live in and they
    are not willing to relocate. 'Remote' without a country restriction always passes."""
    if getattr(profile, "relocate", False):
        return True
    user = _profile_country(profile)
    restricted = _restricted_countries(location, description)
    if restricted and user not in restricted:
        # EU-wide remote is fine for an EU resident even if e.g. Germany is also listed
        if not (user in _EU_COUNTRIES
                and _EU_REGION_RE.search(f"{location or ''} {description or ''}")):
            return False
    if _RELOC_RE.search(description or "") and restricted != {user}:
        return False    # "relocation required" — and the destination isn't (only) their country
    return True


# Dealbreaker negations — embeddings handle these badly, rules don't ("no remote work",
# "this is NOT a remote position", "office-based role", "изисква присъствие в офиса").
_ONSITE_ONLY_RE = re.compile(
    r"\b(no remote|not a remote|onsite only|on-site only|office[- ]based|"
    r"fully (?:in[- ])?office|само (?:на място|в офис)|присъствие в офиса|"
    r"без (?:възможност за )?дистанционна)\b", re.I)

# Hybrid = part-office. Not "remote", so a remote-only seeker shouldn't get these. The signal
# often lives only in the DESCRIPTION (dev.bg's feed carries no location field, so location is
# empty and location_ok can't judge). Full-remote phrasing overrides — a posting that ALSO
# offers 100% remote is fine for a remote seeker, so it's not flagged.
_HYBRID_RE = re.compile(
    r"\bhybrid\b|хибрид|"
    r"\d+\s*days?\s*(?:a\s*week\s*|per\s*week\s*|in\s*|from\s*|at\s*)+(?:the\s*)?office|"
    r"дни\s*(?:в|от)\s*офиса", re.I)
_FULLY_REMOTE_RE = re.compile(
    r"\b(?:fully|100\s*%|completely|entirely)[-\s]remote\b|\bremote[-\s]first\b|"
    r"изцяло\s*дистанционно|напълно\s*дистанционно", re.I)


def onsite_only(description: str) -> bool:
    return bool(_ONSITE_ONLY_RE.search(description or ""))


def is_hybrid(text: str) -> bool:
    """A hybrid (part-office) posting — office presence required some days, so NOT remote. A
    posting that also states full/100% remote isn't flagged (a remote seeker takes that option)."""
    text = text or ""
    if _FULLY_REMOTE_RE.search(text):
        return False
    return bool(_HYBRID_RE.search(text))


def location_ok(profile, location: str) -> bool:
    remote_pref = (profile.remote_pref or "any").lower()
    loc = (location or "").strip()
    if remote_pref == "any" or not loc:
        return True                       # no constraint, or unknown location -> don't hide
    if _has(loc, _REMOTE):
        return True                       # a remote posting suits remote/hybrid/onsite alike
    # onsite posting: keep it only if it's in one of the candidate's preferred locations
    pref = _tokens(profile.location_pref) - {"remote", "hybrid", "onsite", "any"}
    if pref:
        return bool(_tokens(loc) & pref)
    # no preferred cities given: a remote/hybrid candidate can't take an onsite role -> drop it;
    # an onsite-seeking candidate with no city given, we can't judge -> keep.
    return remote_pref not in ("remote", "hybrid")


def seniority_ok(profile, title: str) -> bool:
    """Hard filter — only the clearest category mismatch: a people-management role for an IC
    candidate. Level mismatches (junior↔senior) are handled softly by seniority_factor, so a
    slightly-off level is down-weighted, not hidden."""
    return not (_posting_is_mgmt(title) and not _profile_wants_mgmt(profile))


def seniority_factor(profile, title: str, *, underqualified: float = 0.6,
                     overqualified: float = 0.75) -> float:
    """Soft multiplier for a level mismatch the hard filter lets through:
    - a senior/lead/principal role for a junior candidate -> under-qualified (they won't get it);
    - a junior/intern role for a senior candidate -> over-qualified (they likely don't want it).
    Mid-level or matching -> 1.0."""
    pl, ql = _posting_level(title), _profile_level(profile)
    if pl == 2 and ql == 0:
        return underqualified
    if pl == 0 and ql == 2:
        return overqualified
    return 1.0


def passes_hard_filters(profile, title: str, location: str, description: str = "") -> tuple[bool, str]:
    """Return (passes, reason). reason is '' when it passes, else 'location' / 'seniority'."""
    if not location_ok(profile, location):
        return False, "location"
    # a "remote"-labeled posting whose text says otherwise is an onsite/hybrid posting. The
    # hybrid signal often lives ONLY in the description (dev.bg has no location field), so
    # location_ok can't see it — catch it here for a remote-only seeker.
    if (profile.remote_pref or "").lower() == "remote" and (
            onsite_only(description) or is_hybrid(f"{location} {description}")):
        return False, "location"
    if not geo_ok(profile, location, description):
        return False, "location"
    if not seniority_ok(profile, title):
        return False, "seniority"
    return True, ""
