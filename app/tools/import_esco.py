"""Load the ESCO occupation taxonomy (pilot verticals) into the DB via the ESCO REST API.

Stage-2 backbone for the hierarchical onboarding (taxonomy.py docstring): category -> subcategory
-> occupation -> essential/optional skills, with BG + EN labels straight from ESCO. We pull only
the pilot verticals (finance / healthcare / sales) so the dataset stays small and matching can be
validated on non-tech professions before scaling to all ~3000 occupations.

Idempotent: everything upserts by esco_uri / isco_code, so a re-run resumes and refreshes.

    python -m app.tools.import_esco                 # all pilot verticals
    python -m app.tools.import_esco finance         # one vertical
    python -m app.tools.import_esco --calls 500     # cap API calls (safety)
"""
import sys
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data.db import SessionLocal, engine, Base
from ..data.models import OccupationGroup, Occupation, TaxonomySkill, OccupationSkill

API = "https://ec.europa.eu/esco/api"

# Platform UI languages that ESCO actually carries (ru/uk aren't EU languages -> read-side falls
# back to en). One occupation/group/skill fetch returns preferredLabel in all of them at once.
LANGS = ("en", "bg", "de", "el", "es", "fr", "hr", "it", "nl", "pl", "ro")


def _labels(pref: dict | None, fallback: str = "") -> dict:
    out = {lang: pref[lang] for lang in LANGS if (pref or {}).get(lang)}
    if not out and fallback:
        out["en"] = fallback
    return out

# vertical -> ISCO group anchors (ESCO concept codes) to descend from.
VERTICALS: dict[str, tuple[str, ...]] = {
    "finance":    ("241", "331"),   # Finance professionals + financial associate professionals
    "healthcare": ("22",),          # Health professionals (doctors, nursing, pharmacy, therapy…)
    "sales":      ("243", "522"),   # Sales/marketing/PR professionals + shop salespersons
    "ict":        ("25", "35"),     # ICT professionals + technicians — keeps IT in the unified flow
}

# Full-taxonomy mode: descend ALL ISCO major groups and bucket each occupation into a
# user-friendly vertical by its ISCO code (longest prefix wins). Covers every profession.
_ISCO_VERTICAL: dict[str, str] = {
    "01": "military", "02": "military", "03": "military",
    "11": "management", "12": "management", "13": "management", "14": "management",
    "21": "engineering", "31": "engineering",
    "22": "healthcare", "32": "healthcare", "53": "healthcare",
    "23": "education",
    "241": "finance", "331": "finance",
    "243": "sales", "332": "sales", "52": "sales", "95": "sales",
    "25": "ict", "35": "ict",
    "26": "legal_culture", "34": "legal_culture",
    "242": "admin", "41": "admin", "42": "admin", "43": "admin", "44": "admin",
    "333": "admin", "334": "admin", "335": "admin",
    "51": "personal_services", "54": "personal_services",
    "61": "agriculture", "62": "agriculture", "63": "agriculture", "92": "agriculture",
    "71": "construction",
    "72": "crafts", "73": "crafts", "74": "crafts", "75": "crafts",
    "81": "machine_ops", "82": "machine_ops", "83": "machine_ops",
    "91": "elementary", "93": "elementary", "94": "elementary", "96": "elementary",
}
_MAJOR_GROUPS = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")


def _vertical_of(code: str) -> str:
    for n in (3, 2):
        if code[:n] in _ISCO_VERTICAL:
            return _ISCO_VERTICAL[code[:n]]
    return "other"


def _isco_from_uri(uri: str) -> str:
    # http://data.europa.eu/esco/isco/C2411 -> 2411
    return uri.rsplit("/", 1)[-1].lstrip("C")


class Esco:
    """Tiny polite ESCO API client with a hard call budget (network is the cost here)."""
    def __init__(self, budget: int, delay: float = 0.1):
        self.budget, self.delay, self.calls = budget, delay, 0
        self._c = httpx.Client(timeout=25.0, headers={"Accept": "application/json"})

    def get(self, path: str, **params) -> dict | None:
        if self.calls >= self.budget:
            raise RuntimeError(f"ESCO call budget exhausted ({self.budget})")
        if self.calls:
            time.sleep(self.delay)
        self.calls += 1
        try:
            r = self._c.get(f"{API}{path}", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — one bad node must not abort the whole load
            print(f"  ! {path} {params.get('uri','')[-24:]}: {e}")
            return None

    def links(self, node: dict, rel: str) -> list[dict]:
        return (node.get("_links", {}) or {}).get(rel, []) or []


def _upsert_group(db: Session, code: str, parent: str | None, node: dict, vertical: str) -> None:
    row = db.execute(select(OccupationGroup).where(
        OccupationGroup.isco_code == code)).scalar_one_or_none()
    if row is None:
        row = OccupationGroup(isco_code=code)
        db.add(row)
    row.parent_code, row.level = parent, len(code)
    row.vertical = vertical or _vertical_of(code)
    row.labels = _labels(node.get("preferredLabel"), node.get("title", ""))


def _skill_row(db: Session, esco: Esco, cache: dict, uri: str, fallback: str) -> TaxonomySkill:
    """Get-or-create a skill; on first sight fetch its resource once for all-language labels."""
    row = cache.get(uri)
    if row is not None:
        return row
    row = db.execute(select(TaxonomySkill).where(
        TaxonomySkill.esco_uri == uri)).scalar_one_or_none()
    if row is None:
        res = esco.get("/resource/skill", uri=uri, language="en")
        row = TaxonomySkill(esco_uri=uri, labels=_labels((res or {}).get("preferredLabel"), fallback))
        db.add(row)
        db.flush()
    cache[uri] = row
    return row


def _upsert_occupation(db: Session, esco: Esco, uri: str, isco: str, vertical: str,
                       skill_cache: dict) -> bool:
    node = esco.get("/resource/occupation", uri=uri, language="en")
    if not node:
        return False
    occ = db.execute(select(Occupation).where(Occupation.esco_uri == uri)).scalar_one_or_none()
    if occ is None:
        occ = Occupation(esco_uri=uri)
        db.add(occ)
    occ.isco_code = isco
    occ.vertical = vertical or _vertical_of(isco)
    occ.labels = _labels(node.get("preferredLabel"), node.get("title", ""))
    db.flush()

    existing = {os.skill.esco_uri for os in occ.skills}
    for rel, essential in (("hasEssentialSkill", True), ("hasOptionalSkill", False)):
        for s in esco.links(node, rel):
            suri = s["uri"]
            skill = _skill_row(db, esco, skill_cache, suri, s.get("title", ""))
            if suri not in existing:
                db.add(OccupationSkill(occupation_id=occ.id, skill_id=skill.id, essential=essential))
                existing.add(suri)
    return True


def _descend(db: Session, esco: Esco, code: str, parent: str | None, vertical: str,
             seen_groups: set, occ_uris: dict) -> None:
    """Walk an ISCO group subtree: record groups, collect (occupation uri -> leaf isco code)."""
    if code in seen_groups:
        return
    seen_groups.add(code)
    node = esco.get("/resource/concept", uri=f"http://data.europa.eu/esco/isco/C{code}", language="en")
    if not node:
        return
    _upsert_group(db, code, parent, node, vertical)
    for child in esco.links(node, "narrowerConcept"):
        _descend(db, esco, _isco_from_uri(child["uri"]), code, vertical, seen_groups, occ_uris)
    for occ in esco.links(node, "narrowerOccupation"):
        _descend_occ(esco, occ["uri"], code, occ_uris)


def _descend_occ(esco: Esco, uri: str, isco_code: str, occ_uris: dict) -> None:
    """Recurse an occupation's narrowerOccupation subtree. ESCO nests specialised roles under a
    broader one (e.g. 'software developer' -> 'mobile app developer'); the ISCO-group walk alone
    only reaches the ~1700 top occupations that hang directly off a group, missing the ~1200 deeper
    specialisations. Fetch each occupation once here to read its children (it's fetched again in the
    upsert phase for labels/skills — the call budget covers it)."""
    if uri in occ_uris:
        return
    occ_uris[uri] = isco_code
    if len(occ_uris) % 200 == 0:
        print(f"  traversed {len(occ_uris)} occupations...", flush=True)
    node = esco.get("/resource/occupation", uri=uri, language="en")
    if not node:
        return
    for child in esco.links(node, "narrowerOccupation"):
        _descend_occ(esco, child["uri"], isco_code, occ_uris)


def run(session_factory=SessionLocal, verticals: tuple[str, ...] | None = None,
        call_budget: int = 12000) -> dict:
    Base.metadata.create_all(bind=engine)
    verticals = verticals or tuple(VERTICALS)
    esco = Esco(budget=call_budget)
    stats = {"groups": 0, "occupations": 0, "skills": 0}
    skill_cache: dict = {}                         # shared across verticals -> each skill fetched once
    # (label, anchors, vertical-arg): "all" is ONE pass over every ISCO major group, each occupation
    # bucketed by its code (vertical=None -> derived); named verticals use their curated anchors.
    if "all" in verticals:
        passes = [("all", _MAJOR_GROUPS, None)]
    else:
        passes = [(v, VERTICALS[v], v) for v in verticals]
    with session_factory() as db:
        for label, anchors, vertical in passes:
            occ_uris: dict[str, str] = {}
            seen: set[str] = set()
            for anchor in anchors:
                _descend(db, esco, anchor, None, vertical, seen, occ_uris)
            db.commit()
            print(f"[{label}] {len(seen)} groups, {len(occ_uris)} occupations", flush=True)
            done = 0
            for uri, isco in occ_uris.items():
                if _upsert_occupation(db, esco, uri, isco, vertical, skill_cache):
                    done += 1
                if done % 50 == 0:
                    db.commit()
                    print(f"  {label}: {done}/{len(occ_uris)}", flush=True)
            db.commit()
            stats["groups"] += len(seen)
            stats["occupations"] += done
        stats["skills"] = db.execute(select(TaxonomySkill.id)).scalars().all().__len__()
    stats["api_calls"] = esco.calls
    print(f"DONE {stats}")
    return stats


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    budget = 4000
    if "--calls" in args:
        i = args.index("--calls")
        budget = int(args[i + 1])
        del args[i:i + 2]
    if "all" in args:
        vs = ("all",)                              # full taxonomy — every ISCO major group
    else:
        vs = tuple(a for a in args if a in VERTICALS) or None
    run(verticals=vs, call_budget=budget)
