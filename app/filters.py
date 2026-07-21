"""Hard filters applied BEFORE the % score (ARCHITECTURE §5).

A posting that fails location or seniority compatibility is dropped, not shown — no amount of
semantic similarity should surface an Engineering Manager role to an Android IC, or an onsite
role in another city to a remote-only candidate. Rules-based, no LLM. The candidate's *intent*
comes from their profile (target_roles / remote_pref / location_pref), so the user controls the
filters implicitly by how they describe what they want.
"""
import re

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-Я0-9\+\#\.]+")

# Title cues. "lead"/"principal"/"staff" read as senior IC, not management — only real people-
# management titles go here, so e.g. "Tech Lead" is not treated as a manager role.
_MGMT = ("manager", "head of", "director", "vice president", " vp", "vp ", "chief",
         "team lead", "people lead", "engineering lead")
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


def location_ok(profile, location: str) -> bool:
    remote_pref = (profile.remote_pref or "any").lower()
    loc = (location or "").strip()
    if remote_pref == "any" or not loc:
        return True                       # no constraint, or unknown location -> don't hide
    if _has(loc, _REMOTE):
        return True                       # a remote posting suits remote/hybrid/onsite alike
    # onsite posting: keep it only if it's in one of the candidate's preferred locations
    pref = _tokens(profile.location_pref) - {"remote", "hybrid", "onsite", "any"}
    if not pref:
        return True
    return bool(_tokens(loc) & pref)


def seniority_ok(profile, title: str) -> bool:
    if _posting_is_mgmt(title) and not _profile_wants_mgmt(profile):
        return False                      # management role, candidate is an IC
    if _posting_level(title) == 0 and _profile_level(profile) == 2:
        return False                      # junior/intern role, candidate is senior
    return True


def passes_hard_filters(profile, title: str, location: str, description: str = "") -> tuple[bool, str]:
    """Return (passes, reason). reason is '' when it passes, else 'location' / 'seniority'."""
    if not location_ok(profile, location):
        return False, "location"
    if not seniority_ok(profile, title):
        return False, "seniority"
    return True, ""
