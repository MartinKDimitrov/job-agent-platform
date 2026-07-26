"""Aggregator fallback — keep collecting via Careerjet + Jooble when Adzuna is rate-limited.

Adzuna's category bulk pull is the primary firehose, but its trial quota throttles (503s). When
it stalls, this keeps the index growing through the other two aggregators. They're keyword-only
(no taxonomy like Adzuna), so we sweep a broad list of profession KEYWORDS across sectors to
approximate "all professions".

- Careerjet = the workhorse: generous, one call per (term × locale) over all 8 markets incl. BG.
- Jooble = used sparingly: its free tier is **500 requests TOTAL**, so it's capped hard per run.

Silent no-op for a source whose key isn't set. Fetch + persist only (dedup); enrichment/retire
stay in run_ingest_maintenance, run separately.
"""
from __future__ import annotations

import time

from ...data.sources import careerjet, jooble
from .search import persist_postings

# Broad profession keywords spanning sectors — the keyword-API stand-in for Adzuna's taxonomy.
PROFESSION_TERMS = [
    "software developer", "data analyst", "devops engineer", "qa engineer", "product manager",
    "project manager", "accountant", "financial analyst", "auditor", "sales representative",
    "account manager", "marketing manager", "customer service", "human resources", "recruiter",
    "administrator", "office manager", "nurse", "doctor", "pharmacist", "care worker", "teacher",
    "mechanical engineer", "electrical engineer", "civil engineer", "electrician", "plumber",
    "welder", "driver", "warehouse operative", "logistics coordinator", "chef", "waiter",
    "retail assistant", "cleaner", "security officer", "lawyer", "graphic designer", "architect",
    "research scientist", "social worker", "construction worker",
]


def run_aggregator_fallback(session_factory, *, terms: list[str] | None = None,
                            careerjet_terms: int = 15, jooble_terms: int = 6,
                            sleep=time.sleep) -> dict:
    """Sweep Careerjet (primary) + Jooble (capped) over profession keywords and persist.

    ``careerjet_terms`` / ``jooble_terms`` bound how many keywords each source queries this run —
    Jooble stays small to protect its 500-request lifetime cap. Returns per-source added counts.
    """
    terms = terms or PROFESSION_TERMS
    cj_added = jb_added = cj_terms = jb_terms = 0

    # Careerjet — term × all locales (handled inside careerjet.fetch), capped in term count.
    for term in terms[:max(0, careerjet_terms)]:
        posts = careerjet.fetch(search_terms=[term], sleep=sleep)
        cj_terms += 1
        if posts:
            with session_factory() as db:
                cj_added += persist_postings(db, posts)["added"]
                db.commit()

    # Jooble — sparing (500 TOTAL free cap): a handful of terms only.
    for term in terms[:max(0, jooble_terms)]:
        posts = jooble.fetch(search_terms=[term], sleep=sleep)
        jb_terms += 1
        if posts:
            with session_factory() as db:
                jb_added += persist_postings(db, posts)["added"]
                db.commit()

    return {"careerjet_added": cj_added, "jooble_added": jb_added,
            "careerjet_terms": cj_terms, "jooble_terms": jb_terms,
            "total_added": cj_added + jb_added}
