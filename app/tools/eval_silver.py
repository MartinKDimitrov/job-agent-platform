"""Silver-label matching eval — role-family auto-graded, at scale.

`eval_matching.py` ranks a small HAND-graded set (3 profiles / ~37 postings): precise, but far
too small to separate close choices (a model or threshold change). This tool grades EVERY
long-description live posting against a panel of profiles using `role_family` as the relevance
oracle — overlap = 2 (same discipline), soft-conflict = 1 (adjacent), else = 0 — so it scales to
tens of thousands of postings and can decide close calls with confidence that 3 profiles cannot.

    python -m app.tools.eval_silver                    # production config (asym_clean, e5-small)
    python -m app.tools.eval_silver --limit 10000      # cap the posting pool (faster)
    python -m app.tools.eval_silver --variants         # sym_raw vs asym_clean
    python -m app.tools.eval_silver --compare-models   # e5-small vs e5-base (slow: re-embeds)

Silver labels measure "does the ranker put SAME-ROLE postings on top", not fine within-role
relevance. Use it for RELATIVE comparisons under identical labels (A vs B, model vs model), never
as an absolute quality bar. Reproducible; needs the staging tunnel. The 2026-08-01 run that showed
e5-base buys no gain over e5-small at ~4x cost was this harness (see the embedding-model memory).
"""
from __future__ import annotations

import sys
import time

from ..core.config import settings
from ..domain.extraction import extract_requirements
from ..domain.role_family import conflict, families
from ..domain.scoring import blend
from .eval_matching import (_clean_text, _coverage, _profile_text,
                            ndcg_at, precision_at)

# A panel spanning the role families the platform serves — tech AND trades/finance/health/sales,
# so the eval never over-fits to software roles. target_roles drives both the label oracle and the
# embedded profile text; skills/experience enrich the embedding and keyword coverage.
PROFILES: dict[str, dict] = {
    "backend": {"target_roles": "Backend Developer, Software Engineer",
                "skills": "Python, Go, PostgreSQL, Kubernetes, AWS, REST, microservices"},
    "ml": {"target_roles": "Machine Learning Engineer, AI Engineer",
           "skills": "Python, PyTorch, scikit-learn, LLM, MLOps, SQL, Docker"},
    "android": {"target_roles": "Android Developer",
                "skills": "Kotlin, Java, Jetpack Compose, Coroutines, MVVM, Android SDK"},
    "frontend": {"target_roles": "Frontend Developer, React Developer",
                 "skills": "JavaScript, TypeScript, React, CSS, HTML, Redux"},
    "devops": {"target_roles": "DevOps Engineer, SRE",
               "skills": "Kubernetes, Terraform, AWS, CI/CD, Docker, Prometheus, Linux"},
    "data": {"target_roles": "Data Analyst, Data Engineer",
             "skills": "SQL, Python, pandas, Spark, dbt, Tableau, ETL"},
    "accountant": {"target_roles": "Accountant, bookkeeper",
                   "skills": "accounting, IFRS, tax, payroll, Excel, reconciliation, audit"},
    "sales": {"target_roles": "Sales Manager, Account Executive",
              "skills": "B2B sales, CRM, negotiation, account management, lead generation"},
    "welder": {"target_roles": "Welder",
               "skills": "MIG MAG welding, metal fabrication, blueprint reading, grinding"},
    "construction": {"target_roles": "Construction Worker, concrete finisher",
                     "skills": "concrete, formwork, rebar, masonry, site safety"},
    "driver": {"target_roles": "Truck Driver, Delivery Driver",
               "skills": "driving licence C+E, logistics, route planning, cargo"},
    "nurse": {"target_roles": "Nurse, Healthcare Assistant",
              "skills": "patient care, nursing, medication, clinical, vital signs"},
}

# The two E5 modes the harness knows. Production is asym_clean (see scoring.posting_embed_text +
# embed_passage / embed_query, EMBED_VERSION "e5-asym-clean-v2").
_VARIANTS = {
    "sym_raw":    {"post_input": "raw",   "post_prefix": "query: ",   "prof_prefix": "query: "},
    "asym_clean": {"post_input": "clean", "post_prefix": "passage: ", "prof_prefix": "query: "},
}


def silver_grade(profile_families, title: str) -> int:
    """role_family relevance oracle: 2 = same discipline, 1 = adjacent (soft), 0 = unrelated /
    unclassifiable title."""
    jf = families(title)
    if not jf:
        return 0
    if profile_families & jf:
        return 2
    return 1 if conflict(profile_families, jf) == "soft" else 0


def _average_precision(ranked_grades: list[int], total_relevant: int) -> float:
    if not total_relevant:
        return 0.0
    hits = 0
    acc = 0.0
    for i, g in enumerate(ranked_grades):
        if g >= 2:
            hits += 1
            acc += hits / (i + 1)
    return acc / total_relevant


def _recall_at(ranked_grades: list[int], k: int, total_relevant: int) -> float:
    if not total_relevant:
        return 0.0
    return sum(1 for g in ranked_grades[:k] if g >= 2) / total_relevant


def _load_postings(min_len: int, limit: int | None) -> list[dict]:
    from sqlalchemy import func, select

    from ..data.db import SessionLocal
    from ..data.models import Posting
    q = (select(Posting.id, Posting.title, Posting.description)
         .where(Posting.is_live.is_(True), func.length(Posting.description) > min_len))
    if limit:
        q = q.limit(limit)
    with SessionLocal() as db:
        return [{"id": pid, "title": t or "", "description": d or ""}
                for pid, t, d in db.execute(q)]


def _batch_encoder(model_name: str):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)

    def enc(texts: list[str], prefix: str):
        return model.encode([prefix + t for t in texts],
                            normalize_embeddings=True, batch_size=128, show_progress_bar=False)
    return enc


def run(min_len: int = 800, limit: int | None = None, model_name: str | None = None,
        variants: tuple[str, ...] = ("asym_clean",), log=print) -> dict:
    import numpy as np

    model_name = model_name or settings.e5_model
    posts = _load_postings(min_len, limit)
    n = len(posts)
    log(f"postings: {n}  |  model: {model_name.split('/')[-1]}  |  variants: {list(variants)}")

    reqs = [extract_requirements(p["description"]) for p in posts]
    raw = [p["description"] or p["title"] for p in posts]
    clean = [_clean_text(posts[i], reqs[i]) for i in range(n)]
    jfam_titles = [p["title"] for p in posts]

    # silver labels + model-independent keyword coverage, once per profile
    labels: dict[str, list[int]] = {}
    total_rel: dict[str, int] = {}
    cover: dict[str, list[float]] = {}
    for key, prof in PROFILES.items():
        pf = families(prof["target_roles"])
        labels[key] = [silver_grade(pf, t) for t in jfam_titles]
        total_rel[key] = sum(1 for g in labels[key] if g >= 2)
        ptext = _profile_text(prof)
        cover[key] = [_coverage(ptext, reqs[i]) or 0.0 for i in range(n)]
    log("silver grade-2 per profile: "
        + ", ".join(f"{k}={total_rel[k]}" for k in PROFILES))

    enc = _batch_encoder(model_name)
    post_vecs = {"raw": enc(raw, "query: "), "clean": enc(clean, "passage: ")}
    out: dict[str, dict] = {}
    for vname in variants:
        spec = _VARIANTS[vname]
        pv_all = post_vecs[spec["post_input"]]
        agg = {"ndcg@10": [], "p@5": [], "map": [], "recall@20": []}
        for key, prof in PROFILES.items():
            profile_vec = enc([_profile_text(prof)], spec["prof_prefix"])[0]
            cos = pv_all @ profile_vec
            sem = np.clip((cos - 0.6) / 0.35, 0.0, 1.0)   # matches eval_matching._sem_pct
            scores = np.array([blend(float(sem[i]), cover[key][i]) or 0.0 for i in range(n)])
            ranked = [labels[key][i] for i in np.argsort(-scores)]
            agg["ndcg@10"].append(ndcg_at(ranked, 10))
            agg["p@5"].append(precision_at(ranked, 5))
            agg["map"].append(_average_precision(ranked, total_rel[key]))
            agg["recall@20"].append(_recall_at(ranked, 20, total_rel[key]))
        out[vname] = {m: round(sum(v) / len(v), 4) for m, v in agg.items()}
    return out


def main(argv: list[str]) -> None:
    limit = None
    variants = ("asym_clean",)
    models = [settings.e5_model]
    for i, a in enumerate(argv):
        if a == "--limit":
            limit = int(argv[i + 1])
        elif a == "--variants":
            variants = ("sym_raw", "asym_clean")
        elif a == "--compare-models":
            models = ["intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"]
    for model in models:
        t0 = time.time()
        res = run(limit=limit, model_name=model, variants=variants)
        print(f"\n=== {model.split('/')[-1]}  ({time.time() - t0:.0f}s) ===")
        for vname, m in res.items():
            print(f"  {vname:11} NDCG@10={m['ndcg@10']:.3f}  P@5={m['p@5']:.3f}  "
                  f"MAP={m['map']:.3f}  Recall@20={m['recall@20']:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
