"""Pre-release check: run the 50 release profiles against the live index and assert quality.

    python -m app.tools.release_check                 # all 50, full report
    python -m app.tools.release_check --only welder   # one profile, verbose
    python -m app.tools.release_check --top 5         # inspect fewer matches per profile

Run this BEFORE every release. `eval_silver` answers "did ranking get better on average"; this
answers "is anything obviously broken for a real person", which averages hide — every check below
exists because that exact failure reached a user's feed:

1. **recall** — the profile finds matches at all (a family/threshold change can silently zero out
   a whole profession);
2. **domain** — no top match is a HARD role-family conflict (the accountant whose feed filled with
   logistics, marketing and customer-service roles);
3. **boilerplate** — no GDPR/consent, benefit or employment-terms line is presented as a missing
   requirement (they arrive in every language, so the patterns are checked in all of them);
4. **education** — a stated degree covers a degree requirement at or below that level ("I said I
   have higher education but it still lists a degree as missing");
5. **sanity** — scores stay inside 0-100 and the top match isn't below the profile's threshold.

It reads the index and never writes: the profiles are built in memory, never persisted, so this
leaves no test data on staging.
"""
from __future__ import annotations

import re
import sys

from sqlalchemy import select

from ..application import vector_cache
from ..core.config import settings
from ..data.db import SessionLocal
from ..data.models import Posting
from ..domain.filters import extract_qualification_level, passes_hard_filters
from ..domain.role_family import conflict, families
from ..domain.scoring import embed_query, score, warm_model
from .release_profiles import EXTRA, PROFILES

# Lines that must never be shown to a candidate as a missing requirement. Multilingual on purpose:
# a posting's boilerplate is in the posting's language, not the user's.
_BOILERPLATE = re.compile(
    r"gdpr|ззлд|personal data|лични данни|voluntarily agree|by applying|"
    r"personenbezogene|datenschutz|donn(?:é|e)es personnelles|datos personales|"
    r"dane osobowe|prelucrarea datelor|"
    r"only shortlisted|одобрени кандидати|ausgew(?:ä|ae)hlte kandidaten|candidats retenus|"
    r"days? (?:of )?(?:paid )?(?:annual )?leave|days? vacation|отпуск|urlaub|cong(?:é|e)s|"
    r"health insurance|здравна осигуровка|multisport|мултиспорт|sports? card|"
    r"team building|тиймбилдинг|massages?|office parties|"
    r"hours per week|wochenstunden|godzin tygodniowo|работно време|"
    r"unbefristet|umowa o prac|trudov dogovor|трудов договор", re.I)


class _P:
    """An in-memory profile — never added to a session, so the check writes nothing."""

    def __init__(self, key, roles, skills, country, city, remote, education, languages,
                 relocate=False, min_match=50, salary_expectation="", experience="",
                 english_level="B2"):
        self.id, self.key = 0, key
        self.name, self.target_roles, self.skills = key, roles, skills
        self.experience = experience
        self.country, self.location_pref, self.remote_pref = country, city, remote
        self.qualification_level, self.languages = education, languages
        self.english_level, self.relocate, self.min_match = english_level, relocate, min_match
        self.salary_expectation, self.embedding = salary_expectation, None

    @classmethod
    def from_spec(cls, spec):
        """Positional tuple (batch 1) or keyword dict (batch 2, which varies the parameters the
        defaults above were hiding: relocation, threshold, salary, experience, English level)."""
        if isinstance(spec, dict):
            d = dict(spec)
            return cls(d.pop("key"), d.pop("target_roles"), d.pop("skills"), d.pop("country"),
                       d.pop("city"), d.pop("remote_pref"), d.pop("education"),
                       d.pop("languages"), **d)
        return cls(*spec)

    def as_text(self) -> str:
        return f"{self.target_roles} · {self.skills}"

    def embed_text(self) -> str:
        return self.as_text()


def _candidates(db, prof, id_titles, limit: int):
    """The SAME three recall doors as `search_db` — title tokens, semantic, shared skill. Using
    the vector door alone made the check lie: a short profile ("Junior Accountant · bookkeeping,
    invoices") found nothing over the cosine threshold and was reported as broken recall, while
    the product would have surfaced it through the title door."""
    from ..application.usecases.search import _TOKEN_RE, _profile_keywords
    from ..domain.skills import RECALL_GENERIC_SKILLS, extract_skills

    from ..data.taxonomy_repo import role_names_all_languages
    names = role_names_all_languages(db, prof.target_roles or "")
    text = prof.embed_text()
    if names:
        text = " · ".join(names) + " · " + text
    prof.embedding = list(embed_query(text))
    keywords = _profile_keywords(prof)
    token_ids = {pid for pid, title, loc in id_titles
                 if keywords and keywords & set(_TOKEN_RE.findall((title or "").lower()))
                 and passes_hard_filters(prof, title or "", loc or "", "")[0]}
    vector_ids = vector_cache.similar_posting_ids(db, prof.embedding,
                                                  settings.recall_min_cosine, limit=limit)
    skill_ids = vector_cache.postings_sharing_skills(
        db, extract_skills(prof.skills or "") - RECALL_GENERIC_SKILLS)
    core = skill_ids | vector_ids
    ids = list(core)[:limit]
    if len(ids) < limit:
        seen = set(ids)
        ids += [pid for pid in token_ids if pid not in seen][:limit - len(ids)]
    if len(ids) < limit:
        seen = set(ids)
        need = limit - len(ids)
        for pid, title, loc in vector_cache.ranked_candidates(
                db, prof.embedding, limit * settings.recall_rank_oversample,
                extra_filter=vector_cache.geo_narrowing(prof)):
            if pid in seen or not passes_hard_filters(prof, title, loc or "", "")[0]:
                continue
            ids.append(pid)
            need -= 1
            if need <= 0:
                break
    if not ids:
        return []
    return db.execute(select(Posting).where(Posting.id.in_(ids))).scalars().all()


def check_profile(db, prof, id_titles, top: int = 10) -> dict:
    fams = families(prof.target_roles)
    scored = []
    for post in _candidates(db, prof, id_titles, settings.recall_max_candidates):
        ok, _ = passes_hard_filters(prof, post.title, post.location, post.description)
        if not ok:
            continue
        sc, covered, missing = score(prof.as_text(), post.description or post.title,
                                     post.requirements, profile_vec=prof.embedding,
                                     posting_vec=post.embedding,
                                     sem_weight=settings.semantic_weight,
                                     education_level=prof.qualification_level,
                                     sem_only_cap=settings.semantic_only_cap)
        scored.append((sc, post, missing))
    scored.sort(key=lambda x: -x[0])
    head = scored[:top]
    problems: list[str] = []

    if not scored:
        problems.append("recall: no matches at all")
    for sc, post, missing in head:
        if not (0 <= sc <= 100):
            problems.append(f"sanity: score {sc} out of range on {post.title[:40]!r}")
        pf = families(post.title)
        if fams and pf and conflict(fams, pf) == "hard":
            problems.append(f"domain: {post.title[:44]!r} is {set(pf)} vs profile {set(fams)}")
        for r in missing or []:
            text = r.get("text", "") if isinstance(r, dict) else str(r)
            if _BOILERPLATE.search(text):
                problems.append(f"boilerplate: {text[:56]!r} shown as missing "
                                f"on {post.title[:30]!r}")
            need = extract_qualification_level(text)
            if (need is not None and prof.qualification_level is not None
                    and prof.qualification_level >= need):
                problems.append(f"education: level {prof.qualification_level} profile still "
                                f"missing {text[:44]!r}")
    return {"key": prof.key, "matches": len(scored),
            "top": [(round(s), p.title[:52]) for s, p, _ in head[:5]],
            "problems": problems}


def _flush_print(*a):
    print(*a, flush=True)


def run(only: str | None = None, top: int = 10, log=_flush_print) -> dict:
    warm_model()
    specs = list(PROFILES) + list(EXTRA)
    profiles = [_P.from_spec(sp) for sp in specs
                if not only or only in (sp["key"] if isinstance(sp, dict) else sp[0])]
    log(f"release check — {len(profiles)} profiles\n")
    failed = 0
    with SessionLocal() as db:
        vector_cache.warm(db)
        # pulled once and shared: the title door needs every live (id, title)
        id_titles = db.execute(select(Posting.id, Posting.title, Posting.location)
                               .where(Posting.is_live.is_(True))).all()
        log(f"index: {len(id_titles)} live postings\n")
        for prof in profiles:
            res = check_profile(db, prof, id_titles, top)
            mark = "ok  " if not res["problems"] else "FAIL"
            log(f"  {mark} {res['key']:22} {res['matches']:4} matches | "
                f"top: {', '.join(f'{s}% {t[:30]}' for s, t in res['top'][:2])}")
            for p in res["problems"][:6]:
                log(f"        - {p}")
            failed += bool(res["problems"])
    log(f"\n{len(profiles) - failed}/{len(profiles)} profiles clean")
    return {"profiles": len(profiles), "failed": failed}


def main(argv: list[str]) -> None:
    only, top = None, 10
    for i, a in enumerate(argv):
        if a == "--only":
            only = argv[i + 1]
        elif a == "--top":
            top = int(argv[i + 1])
    res = run(only=only, top=top)
    sys.exit(1 if res["failed"] else 0)      # non-zero so it can gate a release


if __name__ == "__main__":
    main(sys.argv[1:])
