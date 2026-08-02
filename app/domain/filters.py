"""Hard filters applied BEFORE the % score (ARCHITECTURE §5).

A posting that fails location or seniority compatibility is dropped, not shown — no amount of
semantic similarity should surface an Engineering Manager role to an Android IC, or an onsite
role in another city to a remote-only candidate. Rules-based, no LLM. The candidate's *intent*
comes from their profile (target_roles / remote_pref / location_pref), so the user controls the
filters implicitly by how they describe what they want.
"""
import re
from functools import lru_cache

from .role_family import role_family_ok

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
# A role that is itself remote even though the LOCATION field names the employer's city (a Berlin
# company advertising an EU-remote position). Positive phrasings only — "no remote" is handled by
# onsite_only, which callers check first.
_REMOTE_ROLE_RE = re.compile(
    r"\b(?:fully|100\s*%|completely|entirely|permanently)[-\s]*remote\b|\bremote[-\s]first\b|"
    r"\bremote\s*(?:position|role|job|opportunity|work|working)\b|\bwork(?:ing)?\s+from\s+anywhere\b|"
    r"\banywhere\s+in\s+(?:the\s+)?(?:eu|europe)\b|\b(?:eu|europe|european)[-\s]remote\b|"
    r"\bremote\s*\((?:eu|europe|emea)\)|изцяло\s*дистанционно|напълно\s*дистанционно", re.I)
# A limited 'remote for N days/weeks per year' WORKATION perk — an on-site role with a bit of
# remote, NOT a remote work mode ("Remote work from any location worldwide for two weeks annually").
_REMOTE_PERK_RE = re.compile(
    r"\bremote\b[^.]{0,60}?\b(?:one|two|three|four|five|six|\d+)\s*(?:days?|weeks?|months?)\b"
    r"[^.]{0,30}?\b(?:per\s+(?:year|month|quarter)|annually|a\s+year|yearly|each\s+year|/\s*year)\b",
    re.I)


def onsite_only(description: str) -> bool:
    return bool(_ONSITE_ONLY_RE.search(description or ""))


def is_remote(title: str, location: str = "", description: str = "") -> bool:
    """True when the ROLE itself is remote — the location field says so, the title flags it
    ('Android Developer — Remote'), or the text offers full / EU-remote work. A Germany-based
    company advertising an EU-remote position lists 'Berlin' as its location but the role is remote,
    so it must reach a remote seeker. Callers should rule out onsite_only() first."""
    if _has(location or "", _REMOTE):
        return True
    if "remote" in (title or "").lower():
        return True
    text = f"{title or ''} {description or ''}"
    # a limited 'N weeks remote per year' workation perk is not the work mode (unless the text also
    # states a genuine full/EU-remote arrangement elsewhere)
    if _REMOTE_PERK_RE.search(text) and not _FULLY_REMOTE_RE.search(text):
        return False
    return bool(_REMOTE_ROLE_RE.search(text))


# Major Bulgarian + European cities (Latin/local) — used to PLACE a posting whose location field
# is empty (dev.bg carries none) from cues in its text, so the geography model can tell whether a
# job sits in the candidate's preferred city or a different one.
_CITY_ALIASES = {
    "sofia": ("sofia", "софия"), "plovdiv": ("plovdiv", "пловдив"),
    "varna": ("varna", "варна"), "burgas": ("burgas", "бургас"),
    "ruse": ("ruse", "русе"), "stara zagora": ("stara zagora", "стара загора"),
    "pleven": ("pleven", "плевен"), "sliven": ("sliven", "сливен"),
    "dobrich": ("dobrich", "добрич"), "shumen": ("shumen", "шумен"),
    "pernik": ("pernik", "перник"), "haskovo": ("haskovo", "хасково"),
    "pazardzhik": ("pazardzhik", "пазарджик"), "blagoevgrad": ("blagoevgrad", "благоевград"),
    "veliko tarnovo": ("veliko tarnovo", "veliko turnovo", "велико търново"),
    "gabrovo": ("gabrovo", "габрово"), "vratsa": ("vratsa", "враца"),
    "kazanlak": ("kazanlak", "казанлък"), "vidin": ("vidin", "видин"),
    "kardzhali": ("kardzhali", "кърджали"), "montana": ("montana", "монтана"),
    # major EU tech hubs (so a preferred city like Berlin/Amsterdam works, not just BG)
    "berlin": ("berlin",), "munich": ("munich", "münchen", "muenchen"),
    "hamburg": ("hamburg",), "frankfurt": ("frankfurt",), "cologne": ("cologne", "köln"),
    "stuttgart": ("stuttgart",), "duesseldorf": ("düsseldorf", "duesseldorf", "dusseldorf"),
    "paris": ("paris",), "lyon": ("lyon",), "amsterdam": ("amsterdam",),
    "rotterdam": ("rotterdam",), "london": ("london",), "manchester": ("manchester",),
    "madrid": ("madrid",), "barcelona": ("barcelona",), "valencia": ("valencia",),
    "warsaw": ("warsaw", "warszawa"), "krakow": ("krakow", "kraków", "cracow"),
    "wroclaw": ("wroclaw", "wrocław"), "gdansk": ("gdansk", "gdańsk"),
    "vienna": ("vienna", "wien"), "zurich": ("zurich", "zürich"), "geneva": ("geneva", "genève"),
    "milan": ("milan", "milano"), "rome": ("rome", "roma"), "dublin": ("dublin",),
    "lisbon": ("lisbon", "lisboa"), "porto": ("porto",), "prague": ("prague", "praha"),
    "budapest": ("budapest",), "bucharest": ("bucharest", "bucurești", "bucuresti"),
    "athens": ("athens", "αθήνα"), "thessaloniki": ("thessaloniki",),
    "stockholm": ("stockholm",), "copenhagen": ("copenhagen", "københavn"),
    "oslo": ("oslo",), "helsinki": ("helsinki",), "brussels": ("brussels", "bruxelles"),
}
_CITY_RES = {
    c: re.compile(r"(?<![a-zа-я])(?:" + "|".join(re.escape(a) for a in al) + r")(?![a-zа-я])", re.I)
    for c, al in _CITY_ALIASES.items()
}


def cities_in(text: str) -> set[str]:
    """Canonical city keys (BG + major EU) named anywhere in the text."""
    t = text or ""
    return {c for c, rx in _CITY_RES.items() if rx.search(t)}


def is_hybrid(text: str) -> bool:
    """A hybrid (part-office) posting — office presence required some days, so NOT remote. A
    posting that also states full/100% remote isn't flagged (a remote seeker takes that option)."""
    text = text or ""
    if _FULLY_REMOTE_RE.search(text):
        return False
    return bool(_HYBRID_RE.search(text))


# ---- the unified geography model -------------------------------------------------------------
# Two independent axes: WORK-TYPE (remote/hybrid/on-site) is a hard filter; GEOGRAPHY (which
# city/country) is a PRIMARY preference — the preferred place ranks first, a different place is
# secondary (shown only when the candidate will relocate, and then soft-down-weighted).

def _preferred_place_tokens(profile) -> set[str]:
    """The candidate's preferred place as tokens, from their explicit location preference (a city
    like 'Berlin' or a country like 'Germany'). Empty when they named none — then geography places
    no constraint (country ELIGIBILITY, e.g. visa, is handled separately by geo_ok)."""
    return _tokens(profile.location_pref or "") - {"remote", "hybrid", "onsite", "any"}


# ISO codes as aggregators write them ("BG", "Sofia, BG", "DE"). _tokens drops anything under
# three characters, so a bare country code was INVISIBLE to the geo check: the posting fell into
# the "no location given" branch and was judged by whatever city the text mentioned. Measured on
# the release profiles: 16 of a welder's 17 in-country candidates were dropped that way.
_ISO_COUNTRY = {
    "bg": "bulgaria", "de": "germany", "fr": "france", "es": "spain", "it": "italy",
    "nl": "netherlands", "pl": "poland", "ro": "romania", "gr": "greece", "ie": "ireland",
    "at": "austria", "be": "belgium", "ch": "switzerland", "dk": "denmark", "se": "sweden",
    "fi": "finland", "pt": "portugal", "cz": "czechia", "hu": "hungary", "hr": "croatia",
    "uk": "uk", "gb": "uk", "us": "usa",
}
_ISO_RE = re.compile(r"(?:^|[\s,(/])([a-z]{2})(?:[\s,)/]|$)", re.I)


def _location_country(location: str) -> str | None:
    """The country a location field names, via its full name or its ISO code."""
    low = (location or "").lower()
    for key, pat in _ALIAS_RES.items():
        if pat.search(low):
            return key
    for m in _ISO_RE.finditer(low):
        hit = _ISO_COUNTRY.get(m.group(1))
        if hit:
            return hit
    return None


def geo_relation(profile, title: str, location: str, description: str = "") -> str:
    """Where the posting sits vs the candidate's target: 'preferred' | 'elsewhere' | 'unknown'.
    A remote role is location-agnostic -> 'preferred'. Otherwise the place comes from the location
    field (authoritative) or, when empty (dev.bg), from city cues in the text."""
    if _has(location or "", _REMOTE) or (is_remote(title, location, description)
                                         and not onsite_only(description)):
        return "preferred"
    pref = _preferred_place_tokens(profile)                 # ascii tokens (varna, germany…)
    pref_cities = cities_in(profile.location_pref or "")    # canonical city keys — Cyrillic-safe
    if not pref and not pref_cities:
        return "preferred"                        # candidate named no place -> nothing to miss
    loc = location or ""
    ltoks = _tokens(loc)                          # ascii tokens ('Berlin, Germany')
    loc_cities = cities_in(loc)                   # Cyrillic-safe city read ('София' from dev.bg)
    if ltoks or loc_cities:                       # the location field names a place
        if (pref & ltoks) or (pref_cities & loc_cities):
            return "preferred"
        # a country-level match with no city named is still the candidate's country: aggregator
        # postings routinely carry only "BG"/"Bulgaria", and treating those as elsewhere hid the
        # domestic market from every on-site candidate.
        if not loc_cities and _location_country(loc) == _profile_country(profile):
            return "preferred"
        return "elsewhere"
    lc = _location_country(loc)
    if lc is not None:                            # bare country code ("BG", "IE")
        return "preferred" if lc == _profile_country(profile) else "elsewhere"
    # empty location field -> read the city from the text
    found = cities_in(f"{title} {description}")
    if (pref_cities and (pref_cities & found)) or (pref & _tokens(description or "")):
        return "preferred"
    if found and pref_cities and not (found & pref_cities):
        return "elsewhere"
    return "unknown"


def work_type_ok(profile, title: str, location: str, description: str = "") -> bool:
    """Work-TYPE compatibility (remote / hybrid / on-site), independent of WHERE."""
    pref = (profile.remote_pref or "any").lower()
    if pref == "any":
        return True
    loc = location or ""
    text = f"{loc} {description}"
    # a "no remote / not a remote position" note overrides a 'Remote' location label
    remote = not onsite_only(description) and (_has(loc, _REMOTE) or is_remote(title, loc, description))
    hybrid = is_hybrid(text)
    located_onsite = bool(_tokens(loc)) and not _has(loc, _REMOTE)
    if pref == "remote":
        if remote:
            return True
        # they may still accept an on-site role in a city they explicitly named
        city = _tokens(profile.location_pref or "") - {"remote", "hybrid", "onsite", "any"}
        if located_onsite and city and (city & _tokens(loc)):
            return True
        if onsite_only(description) or hybrid or located_onsite:
            return False
        return True                               # unknown (empty loc, no on-site cue) -> keep
    if pref == "hybrid":
        if hybrid or remote:
            return True
        return not onsite_only(description)
    if pref == "onsite":
        if remote and not hybrid:                 # a purely remote role gives no office
            return False
        return True
    return True


def location_ok(profile, location: str, description: str = "") -> bool:
    """GEOGRAPHY gate only (work-TYPE handled by work_type_ok): the place must match the preferred
    city/country, unless the candidate will relocate. Remote / unknown always pass."""
    if geo_relation(profile, "", location, description) == "elsewhere":
        return bool(getattr(profile, "relocate", False))
    return True


def location_factor(profile, title: str, location: str, description: str = "",
                    *, elsewhere: float = 0.8) -> float:
    """Soft multiplier: a role in a DIFFERENT place than the candidate prefers (surfaced only
    because they'll relocate) ranks BELOW their preferred-location roles — relocation is a
    secondary option, not an equal one. 1.0 for preferred / remote / unknown."""
    return elsewhere if geo_relation(profile, title, location, description) == "elsewhere" else 1.0


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


# Formal education/qualification requirement, on the NKPD-2011 level scale (0-8). Highest tier
# explicitly stated in a posting wins, so the list is ordered high -> low. BG + EN cues.
# Education cues per NKPD level, in every language postings arrive in. Substring match on lowered
# text, so each cue must be unambiguous ACROSS languages — the dangerous ones are deliberately
# absent: bare "licence" (FR degree, but "driving licence" is everywhere in trades ads), bare
# "grado" (ES degree, but Italian "in grado di" = "able to"), "mbo" (inside "combo"), "havo"
# (inside "havoc"), bare "bac"/"sss"/"wo". Qualified phrases only.
_EDU_LEVELS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (8, ("phd", "ph.d", "doctoral", "doctorate", "докторска", "доктор на науки",
         "образователна и научна степен",
         "doktorgrad", "doktortitel", "doktorat", "doctorat", "dottorato", "doctorado",
         "doctoraat", "διδακτορικό", "докторская", "докторський")),
    # "master" must be DEGREE-shaped: bare "master" reads a trade's "Master Technician",
    # "master data", "Mastertrainer:in" and "masterplanning" as a Master's degree — measured 9%
    # false positives on level 7, and each one wrongly penalises a less-schooled candidate.
    (7, ("master's", "masters degree", "masters in ", "masters of ", "master degree", "master of ", "master in ", "master or ",
         "master/", "masterabschluss", "masterstudium", "master-abschluss", "master en ",
         "msc", "m.sc", "mba", "магистър", "магистърска",
         "magister", "mastère", "máster", "laurea magistrale", "studia magisterskie",
         "masterat", "magistar", "μεταπτυχιακό", "магистр", "магістр")),
    (6, ("bachelor", "bsc", "b.sc", "university degree", "higher education", "university education",
         "висше образование", "бакалавър", "университетско образование", "университетска степен",
         "hochschulabschluss", "hochschulstudium", "akademischer abschluss",
         "abgeschlossenes studium", "studienabschluss",
         "diplôme universitaire", "études supérieures", "bac+",
         "grado universitario", "licenciatura", "titulación universitaria", "estudios superiores",
         "laurea", "titolo universitario", "universitair", "hbo-opleiding",
         "licencjat", "wyższe wykształcenie", "wykształcenie wyższe", "studia wyższe",
         "licență", "studii superioare", "visoka stručna sprema",
         "πτυχίο", "ανώτατη εκπαίδευση", "высшее образование", "бакалавр", "вища освіта")),
    (5, ("professional qualification", "college degree", "проф. квалификация",
         "професионална квалификация", "полувисше", "колеж",
         "berufsausbildung", "ausbildung", "berufsabschluss", "formation professionnelle", "brevet de technicien",
         "formación profesional", "ciclo formativo", "qualifica professionale",
         "diploma professionale", "mbo-niveau", "technikum", "szkoła policealna",
         "școală postliceală", "calificare profesională", "среднее специальное")),
    (3, ("secondary education", "high school diploma", "средно образование", "средно специално",
         "средно/висше", "средно или висше", "средно и/или висше",
         "abitur", "mittlere reife", "baccalauréat", "bachillerato",
         "educación secundaria", "diploma di maturità", "scuola superiore",
         "middelbare school", "średnie wykształcenie", "matura", "bacalaureat", "studii medii",
         "απολυτήριο λυκείου", "srednja stručna sprema", "среднее образование",
         "середня освіта")),
    (1, ("primary education", "основно образование", "hauptschulabschluss", "école primaire",
         "educación primaria", "podstawowe wykształcenie")),
)


# Cues are matched on WORD BOUNDARIES, not as bare substrings: "bsc" sits inside the German
# "abSChluss" (Hochschul-/Studien-/Berufs-/Masterabschluss), which silently read every German
# posting mentioning a qualification as a bachelor's requirement. Short acronyms (bsc/msc/mba/
# phd) make substring matching untenable, so every cue gets \b...\b.
_EDU_RES: tuple[tuple[int, "re.Pattern"], ...] = tuple(
    (lvl, re.compile(r"\b(?:" + "|".join(re.escape(c) for c in cues) + r")", re.I))
    for lvl, cues in _EDU_LEVELS)


def extract_qualification_level(text: str) -> int | None:
    """The formal education level a posting requires to ENTER it (NKPD scale 0-8), or None when it
    states none. Multilingual keyword match; absence -> None so matching stays conservative.

    When several levels appear we take the LOWEST: "Bachelor's or Master's degree" admits a
    bachelor, so its entry bar is 6, not 7 — reading the highest would penalise candidates the
    posting would actually accept. The same rule makes a stray mention ("after your bachelor…" in
    a PhD ad) err toward NOT penalising, which is the safe direction for a soft factor."""
    t = text or ""
    found = [lvl for lvl, rx in _EDU_RES if rx.search(t)]
    return min(found) if found else None


def qualification_factor(profile, text: str, *, underqualified: float = 0.7, gap: int = 2,
                         need: int | None = None) -> float:
    """Soft down-weight when a posting demands a much higher formal qualification than the profile's
    occupation carries (its NKPD level, set at onboarding). Acts only when BOTH levels are known and
    the posting needs at least `gap` levels more — e.g. a basic-vocational profession (level 2) vs a
    role requiring a university degree (level 6). Unknown either side -> 1.0 (never act)."""
    pql = getattr(profile, "qualification_level", None)
    if pql is None:
        return 1.0
    if need is None:                      # caller passes the COLLECTED level (Posting.education_level)
        need = extract_qualification_level(text)   # fallback: not collected yet / ad-hoc callers
    if need is None:
        return 1.0
    return underqualified if (need - pql) >= gap else 1.0


def passes_hard_filters(profile, title: str, location: str, description: str = "") -> tuple[bool, str]:
    """Return (passes, reason). reason is '' when it passes, else 'location' / 'seniority' / 'role'."""
    # 1. WORK-TYPE (hard): remote / hybrid / on-site compatibility, independent of where.
    if not work_type_ok(profile, title, location, description):
        return False, "location"
    # 2. GEOGRAPHY (hard): a role in a DIFFERENT place than the candidate's preferred city/country
    #    is dropped — unless they'll relocate, in which case it's kept and soft-down-weighted by
    #    location_factor (relocation is a SECONDARY option, ranked below the preferred location).
    rel = geo_relation(profile, title, location, description)
    relocate = getattr(profile, "relocate", False)
    if rel == "elsewhere" and not relocate:
        return False, "location"
    # An on-site / hybrid seeker who NAMED a city and won't relocate needs that city CONFIRMED: a
    # role whose place can't be determined (empty location, no city cue — an unlabelled dev.bg ad)
    # is not a confirmed office in their city, so it's dropped rather than shown on spec.
    if rel == "unknown" and not relocate and (profile.remote_pref or "").lower() == "onsite" \
            and (_preferred_place_tokens(profile) or cities_in(profile.location_pref or "")):
        return False, "location"
    # 3. country eligibility (visa / must-reside restrictions — orthogonal to the city preference).
    if not geo_ok(profile, location, description):
        return False, "location"
    if not seniority_ok(profile, title):
        return False, "seniority"
    # role-family: a QA posting for a Backend candidate (or PM for a Data Scientist) is a
    # different discipline no semantic overlap should surface. Only the clearest, non-adjacent
    # mismatch drops here; adjacent families (Data Scientist↔Data Engineer) are soft-weighted.
    if not role_family_ok(profile, title):
        return False, "role"
    return True, ""
