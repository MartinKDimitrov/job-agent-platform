"""Matching-quality eval harness (Phase 0 of the improvement plan):

    python -m app.tools.eval_matching [evals/matching_v1.json]

Ranks every posting in the hand-labeled dataset for each profile under several VARIANTS
and reports NDCG@10 / Precision@5 against the human grades (0/1/2). This is the artifact
that decides: E5 mode (symmetric vs passage:/query:), raw vs clean embedding input, and
later the recall/near-dup/★-cap thresholds — measured, never by feel.

Variants:
- sym_raw    — today's production: query:+query: over the RAW description
- sym_clean  — query:+query: over title + extracted requirements
- asym_raw   — passage:(doc) / query:(profile) over the RAW description
- asym_clean — passage:/query: over title + extracted requirements
- kw_only    — coverage only, no semantics (sanity baseline)

The blend/coverage side is identical across variants (production formula), so differences
isolate the semantic component. Requires the E5 model (network on first download).
"""
from __future__ import annotations

import json
import math
import sys

from ..domain.extraction import extract_requirements
from ..domain.scoring import _tokens, blend, coverage_ratio, req_weight, requirement_hit


def _profile_text(p: dict) -> str:
    return " · ".join(x for x in (p.get("target_roles"), p.get("skills"),
                                  p.get("experience")) if x)


def _clean_text(post: dict, reqs: list[dict]) -> str:
    parts = [post["title"]] + [r["text"] for r in reqs
                               if r.get("kind") in ("must", "nice", "resp")]
    return "\n".join(parts)


def _embedder():
    from sentence_transformers import SentenceTransformer
    from ..core.config import settings
    model = SentenceTransformer(settings.e5_model)

    def enc(text: str, prefix: str):
        return model.encode(prefix + text, normalize_embeddings=True)
    return enc


def _cos(a, b) -> float:
    return float((a * b).sum())


def _sem_pct(cos: float) -> float:
    return max(0.0, min(1.0, (cos - 0.6) / 0.35))


def _coverage(profile_text: str, reqs: list[dict]) -> float | None:
    toks = _tokens(profile_text)
    return coverage_ratio([(r, requirement_hit(r, profile_text, toks))
                           for r in reqs if req_weight(r) > 0])


def ndcg_at(ranked_grades: list[int], k: int) -> float:
    def dcg(gs):
        return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gs[:k]))
    ideal = dcg(sorted(ranked_grades, reverse=True))
    return dcg(ranked_grades) / ideal if ideal else 0.0


def precision_at(ranked_grades: list[int], k: int) -> float:
    top = ranked_grades[:k]
    return sum(1 for g in top if g == 2) / k if top else 0.0


def run(dataset_path: str = "evals/matching_v1.json") -> dict:
    data = json.load(open(dataset_path))
    postings = {str(p["id"]): p for p in data["postings"]}
    reqs_by_post = {pid: extract_requirements(p["description"])
                    for pid, p in postings.items()}
    enc = _embedder()

    # posting vectors per (input, prefix)
    post_vecs = {}
    for pid, p in postings.items():
        raw, clean = p["description"] or p["title"], _clean_text(p, reqs_by_post[pid])
        post_vecs[pid] = {
            ("raw", "query: "): enc(raw, "query: "),
            ("raw", "passage: "): enc(raw, "passage: "),
            ("clean", "query: "): enc(clean, "query: "),
            ("clean", "passage: "): enc(clean, "passage: "),
        }

    variants = {"sym_raw": ("raw", "query: "), "sym_clean": ("clean", "query: "),
                "asym_raw": ("raw", "passage: "), "asym_clean": ("clean", "passage: "),
                "kw_only": None}
    results: dict[str, dict] = {v: {} for v in variants}

    for prof_key, prof in data["profiles"].items():
        ptext = _profile_text(prof)
        pvec = enc(ptext, "query: ")
        labels = data["labels"][prof_key]
        kw = {pid: _coverage(ptext, reqs_by_post[pid]) for pid in labels}
        for vname, spec in variants.items():
            scored = []
            for pid in labels:
                if spec is None:
                    s = blend(None, kw[pid])
                else:
                    s = blend(_sem_pct(_cos(pvec, post_vecs[pid][spec])), kw[pid])
                scored.append((s, labels[pid]["grade"]))
            ranked = [g for _, g in sorted(scored, key=lambda x: -x[0])]
            results[vname][prof_key] = {"ndcg@10": round(ndcg_at(ranked, 10), 4),
                                        "p@5": round(precision_at(ranked, 5), 4)}

    for vname, per in results.items():
        per["MEAN"] = {"ndcg@10": round(sum(x["ndcg@10"] for k, x in per.items()
                                            if k != "MEAN") / len(data["profiles"]), 4),
                       "p@5": round(sum(x["p@5"] for k, x in per.items()
                                        if k != "MEAN") / len(data["profiles"]), 4)}
    return results


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "evals/matching_v1.json"
    res = run(path)
    profs = [k for k in next(iter(res.values())) if k != "MEAN"]
    header = "variant     " + "".join(f"{p:>22}" for p in profs) + f"{'MEAN':>22}"
    print(header)
    print("-" * len(header))
    for vname, per in res.items():
        row = f"{vname:<12}"
        for p in profs + ["MEAN"]:
            row += f"  ndcg {per[p]['ndcg@10']:.3f} p@5 {per[p]['p@5']:.2f}"
        print(row)
