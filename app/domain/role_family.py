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
                     "software architect", "solution architect", "solutions architect",
                     "cloud architect", "enterprise architect", "data architect", "it architect",
                     "софтуерен архитект",
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
                     "cyber security", "cybersecurity", "information security", "security analyst",
                     "security operations", "application security"),
    "pm":           ("product manager", "product owner", "project manager", "program manager",
                     "delivery manager", "scrum master"),
    "design":       ("ux designer", "ui designer", "product designer", "ux/ui", "ui/ux",
                     "graphic designer", "web designer", "ux researcher"),
    "embedded":     ("embedded", "firmware"),
    "gamedev":      ("game developer", "gameplay", "unreal engine", "unity developer"),
    # ---- non-tech pilot verticals (ESCO): specific profession cues, never bare generics ----
    "finance":      ("accountant", "accounting", "bookkeeper", "bookkeeping", "auditor",
                     "financial analyst", "financial controller", "financial adviser",
                     "financial advisor", "investment adviser", "investment advisor",
                     "credit analyst", "credit officer", "loan officer", "tax advisor",
                     "tax consultant", "tax accountant", "actuary", "treasury", "payroll",
                     "accounts payable", "accounts receivable", "loss adjuster", "underwriter"),
    "healthcare":   ("nurse", "nursing", "physician", "medical doctor", "pharmacist", "dentist",
                     "dental", "physiotherapist", "physical therapist", "podiatrist",
                     "radiographer", "speech therapist", "speech and language therapist",
                     "chiropractor", "veterinarian", "orthoptist", "midwife", "paramedic",
                     "occupational therapist", "recreational therapist", "optometrist",
                     "caregiver", "medical assistant", "healthcare assistant"),
    "sales":        ("salesperson", "sales assistant", "sales representative", "sales engineer",
                     "sales processor", "sales agent", "sales manager", "account executive",
                     "account manager", "business developer", "business development",
                     "shop assistant", "shop supervisor", "specialised seller", "personal shopper",
                     "store manager", "retail", "cashier", "telesales"),
    "marketing":    ("marketing", "marketeer", "brand manager", "advertising", "copywriter",
                     "market research", "public relations", "pr officer", "pr specialist",
                     "community manager", "creative director", "media buyer", "fundraising",
                     "public affairs", "communications specialist"),
    # --- non-tech verticals (ESCO): needed so the ~2900-profession taxonomy gets a family on both
    # sides — without these a construction/trades/etc. profile names NO family, the conflict is
    # 'none', and raw semantic similarity false-matches it to unrelated IT roles (concrete finisher
    # -> DevOps at 90%). Cross-vertical stays a HARD drop (not in _ADJACENT). ---
    "construction": ("concrete finisher", "bricklayer", "brickmason", "stonemason", "mason",
                     "plasterer", "roofer", "scaffolder", "steel fixer", "reinforcing iron",
                     "carpenter", "joiner", "glazier", "tiler", "floor layer", "insulation worker",
                     "construction worker", "construction labourer", "building construction",
                     "paver", "road worker", "formwork", "concrete"),
    "trades":       ("welder", "machinist", "cnc operator", "toolmaker", "metalworker",
                     "sheet metal", "fabricator", "blacksmith", "foundry", "assembler",
                     "production operator", "machine operator", "millwright", "locksmith",
                     "upholsterer", "cabinetmaker", "seamstress", "tailor", "shoemaker",
                     "manufacturing operative", "fitter and turner"),
    "transport":    ("truck driver", "lorry driver", "bus driver", "delivery driver", "taxi driver",
                     "courier", "forklift", "warehouse operative", "warehouse worker", "logistics",
                     "freight", "dispatcher", "crane operator", "heavy equipment operator",
                     "train driver", "chauffeur", "delivery rider"),
    "agriculture":  ("farmer", "farm worker", "agronomist", "gardener", "landscaper",
                     "horticulturist", "forester", "fisherman", "beekeeper", "winemaker",
                     "livestock", "crop grower", "agricultural"),
    "education":    ("technical trainer", "product trainer", "corporate trainer",
                     "teacher", "lecturer", "professor", "tutor", "educator", "teaching assistant",
                     "kindergarten teacher", "school principal", "special needs teacher",
                     "early years", "headteacher"),
    "legal":        ("lawyer", "attorney", "solicitor", "barrister", "paralegal", "notary",
                     "legal counsel", "legal advisor", "legal adviser", "legal assistant",
                     "prosecutor", "magistrate"),
    "admin":        ("administrative assistant", "office clerk", "secretary", "receptionist",
                     "data entry", "office administrator", "personal assistant", "office manager",
                     "filing clerk", "typist", "records clerk"),
    "protective":   ("security guard", "охранител", "wachmann", "wachdienst", "sicherheitsdienst",
                     "agent de sécurité", "vigilante de seguridad", "guardia giurata",
                     "pracownik ochrony", "bodyguard", "невъоръжена охрана", "въоръжена охрана",
                     "физическа охрана"),
    "media":        ("journalist", "журналист", "reporter", "кореспондент", "news editor",
                     "редактор, вестник", "dziennikarz", "periodista", "giornalista"),
    "translation":  ("translator", "interpreter", "преводач", "übersetzer", "dolmetscher",
                     "traducteur", "interprète", "traductor", "intérprete", "traduttore",
                     "tłumacz", "traducător"),
    "veterinary":   ("veterinarian", "veterinary", "ветеринар", "tierarzt", "tierärzt", "vétérinaire",
                     "veterinario", "veterinária", "weterynarz", "лекар, ветеринарна"),
    "sport":        ("fitness", "фитнес", "personal trainer", "личен треньор", "треньор",
                     "инструктор, спорт", "entraîneur", "entrenador personal", "trener personalny",
                     "аеробика", "плувен инструктор"),
    "architecture": ("архитект", "architect", "architekt", "architecte", "arquitecto",
                     "architetto", "урбанист", "urban planner", "landscape architect",
                     "ландшафтен архитект"),
    "hospitality":  ("chef", "cook", "waiter", "waitress", "bartender", "barista",
                     "kitchen assistant", "housekeeper", "hotel receptionist", "concierge",
                     "hairdresser", "barber", "beautician", "cleaner", "cleaning", "butcher",
                     "baker", "pastry", "sommelier", "dishwasher"),
}

# Bulgarian title cues. Profiles are English-keyed (onboarding stores the ESCO English label),
# but posting TITLES arrive in the SOURCE language — so every Bulgarian posting came back
# family-less, `conflict()` said "none", and role-family filtering was inert for the whole BG
# market (owner: logistics, digital-marketing and customer-service roles in an accountant's feed).
# The word-boundary guards are ASCII-only, so a Cyrillic cue matches as a stem — which is what
# Bulgarian morphology needs ("счетовод" covers счетоводител / счетоводството / счетоводна).
_BG_CUES: dict[str, tuple[str, ...]] = {
    "finance":      ("счетовод", "финанс", "банков", "застрахова", "одит", "трз", "данъч",
                     "икономист", "кредитен"),
    "healthcare":   ("медицинск", "лекар", "медицинска сестра", "фармацевт", "стоматолог",
                     "рехабилитатор", "санитар", "акушер", "здравен",
                     "кинезитерапевт", "кинезиолог", "физиотерапевт",
                     "kinesiologist", "kinesiotherapist", "kinesiotherapy", "physiotherapist", "physiotherapy"),
    "sales":        ("продажб", "търговск", "търговец", "магазин", "мърчандайз", "дистрибут",
                     "касиер", "продавач"),
    "marketing":    ("маркетинг", "реклам", "пиар", "копирайт", "бранд мениджър"),
    "construction": ("строител", "зидар", "кофраж", "армату", "бетон", "мазилк", "фаянс",
                     "изолац", "скеле", "пътен строеж"),
    "trades":       ("заварчик", "шлосер", "стругар", "монтьор", "електротехник", "дърводел",
                     "шивач", "механик", "бояджия", "тенекеджия", "мебелист", "оператор машин"),
    "transport":    ("шофьор", "логист", "транспорт", "куриер", "складов", "мотокар", "спедит",
                     "снабдит", "доставки",
                     # drivers/logistics stay hand-written across languages: ESCO files them under
                     # "machine operators" together with food and chemical plant operators, so the
                     # generated cues can't separate them (see build_role_family_i18n).
                     "fahrer", "kraftfahrer", "chauffeur", "conducteur", "conductor", "autista",
                     "kierowca", "şofer", "șofer", "vozač", "οδηγός", "bestuurder",
                     "logistik", "logistique", "logística", "logistyka", "logistica",
                     "spedition", "magazzino", "magazynier", "lagerist"),
    "agriculture":  ("земедел", "агроном", "животновъд", "фермер", "градинар", "горск",
                     "тракторист"),
    "education":    ("учител", "преподавател", "педагог", "възпитател", "обучител",
                     "детегледач"),
    "legal":        ("юрист", "адвокат", "юрисконсулт", "нотариус"),
    "admin":        ("администратор", "офис мениджър", "секретар", "деловодител",
                     "офис асистент", "архивар", "обслужване на клиенти", "кол център"),
    "hospitality":  ("готвач", "сервитьор", "барман", "камериер", "хотел", "ресторант",
                     "кухн", "рецепцион", "аниматор"),
}
for _fam, _cues in _BG_CUES.items():
    FAMILIES[_fam] = FAMILIES[_fam] + _cues

# …and the same problem in the other 10 EU languages postings arrive in. Those cues are DERIVED
# from the ESCO labels rather than hand-written (see app.tools.build_role_family_i18n): a token
# qualifies only when it appears in exactly one ESCO vertical, which is what keeps words like
# "manager"/"specialist" — present in every domain — from tagging everything.
from .role_family_i18n import I18N_CUES  # noqa: E402  (generated data, imported after FAMILIES)

for _fam, _cues in I18N_CUES.items():
    FAMILIES[_fam] = FAMILIES[_fam] + tuple(_cues)

# ESCO's vertical taxonomy files some occupations where our families would not: veterinarians sit
# in the HEALTHCARE vertical (so "Veterinarian" carried healthcare and a midwife ad slipped past
# the vet profile's guard), and sports/fitness workers sit in legal_culture — ISCO 342 — so
# "trainer"/"фитнес" tokens became LEGAL cues and glued fitness profiles to corporate-trainer ads
# through a phantom legal overlap. Strip the misfiled stems from the generated cues; the proper
# families (veterinary, sport) carry them instead.
_MISFILED = {
    "legal": ("trainer", "trener", "треньор", "fitness", "фитнес", "sport", "спорт",
              "coach", "entraîneur", "entrenador", "athlet", "атлет", "instructor",
              "инструктор", "gymnast", "гимнаст"),
    "healthcare": ("veterinar", "ветеринар", "tierarzt", "tierärzt", "weterynarz",
                   "vétérin", "veterin", "животн"),
    # Owner: "бетонджията не е монтажник." ESCO files prefab-element installers under the
    # construction vertical, so "монтажник" became a construction cue and the family floor
    # lifted every fitter/assembly ad to the top of a concrete finisher's feed. Also strip the
    # film-editing "монтаж" tokens legal_culture contributed. Fitter titles simply carry no
    # family — a fitter PROFILE still reaches them through the ESCO title names.
    "construction": ("монтаж",),
    "legal": ("монтаж",),
}
for _fam, _stems in _MISFILED.items():
    FAMILIES[_fam] = tuple(c for c in FAMILIES[_fam] if not any(st in c for st in _stems))

def _family_re(cues: tuple[str, ...]) -> re.Pattern:
    """SHORT cues (<6 chars) are word-bounded on both sides INCLUDING Cyrillic — "одит" was
    matching inside "ръковОДИТел" and tagging a construction manager as finance. LONG cues keep
    the ASCII-only guards so Bulgarian compounds still work ("заварчик" in "електрозаварчик")."""
    short = [c for c in cues if len(c) < 6]
    long_ = [c for c in cues if len(c) >= 6]
    parts = []
    if short:
        parts.append(r"(?<![a-z0-9а-я])(?:" + "|".join(re.escape(c) for c in short)
                     + r")(?![a-z0-9а-я])")
    if long_:
        parts.append(r"(?<![a-z0-9])(?:" + "|".join(re.escape(c) for c in long_)
                     + r")(?![a-z0-9])")
    return re.compile("|".join(parts) or r"(?!x)x", re.I)


_FAMILY_RES: dict[str, re.Pattern] = {fam: _family_re(cues) for fam, cues in FAMILIES.items()}

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
    ("sales", "marketing"),   # sales & marketing overlap heavily — related, not the same
    ("architecture", "construction"),   # architects live on building sites — related, not same
    ("veterinary", "agriculture"),      # livestock vets — related, not the same
    ("media", "marketing"),             # journalism ↔ copywriting/content — related, not same
    # every other non-tech family (finance/healthcare/sales/marketing) is disjoint from the rest
    # and from all IT families -> a hard mismatch (an accountant profile won't see dev/nurse roles).
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
