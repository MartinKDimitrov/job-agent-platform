"""Match scoring via E5 embeddings (local, cheap) with a keyword fallback.

The heavy generative LLM is NOT used here — scoring is embeddings + keyword overlap,
which is near-zero cost and runs locally. See LLM_COST_STRATEGY.md.
"""
import re
from functools import lru_cache

from ..core.config import settings

_model = None


def _get_model():
    """Lazy-load the E5 model. Returns None if sentence-transformers/model unavailable,
    in which case we fall back to keyword scoring."""
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.e5_model)
    except Exception:
        _model = False  # mark as unavailable
    return _model or None


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9\+\#\.]+", (text or "").lower()) if len(t) > 1}


def embed(text: str):
    m = _get_model()
    if not m:
        return None
    # E5 expects a prefix; "query:" is fine for short profile/JD text.
    v = m.encode("query: " + (text or ""), normalize_embeddings=True)
    return v


def _cosine(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a), np.asarray(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / denom)


# Weight of each requirement kind in the keyword-coverage ratio. Must-haves dominate the
# score; nice-to-haves nudge it; responsibilities and soft skills (team player, mindset...)
# are kept for context but never scored as gaps.
_KIND_WEIGHT = {"must": 1.0, "nice": 0.4, "resp": 0.0, "soft": 0.0}


def _norm_reqs(requirements) -> list[dict]:
    """Accept either the new [{'text','kind'}] shape or the old [str] one (older rows / callers)
    so scoring never breaks on legacy data."""
    norm = []
    for r in requirements or []:
        if isinstance(r, dict):
            norm.append({"text": r.get("text", ""), "kind": r.get("kind", "must")})
        else:
            norm.append({"text": str(r), "kind": "must"})
    return norm


def score(profile_text: str, posting_text: str, requirements=None,
          profile_vec=None, posting_vec=None):
    """Return (score_0_100, covered[list[dict]], missing[list[dict]]).

    - Semantic similarity via E5 (if available) drives the base score.
    - Weighted keyword coverage (must-have > nice-to-have) gives covered/missing and a
      fallback score when embeddings are unavailable. Each covered/missing entry keeps its
      {'text','kind'} so the UI can show *why* a posting scored the way it did.
    - `profile_vec` / `posting_vec`: precomputed E5 vectors (DB-cached at ingest time) —
      passing them skips the per-call embedding, which is what makes DB-first search fast.
    """
    reqs = _norm_reqs(requirements)
    p_tok = _tokens(profile_text)
    covered, missing = [], []
    w_cov = w_tot = 0.0
    for r in reqs:
        rtok = _tokens(r["text"])
        hit = bool(rtok and rtok & p_tok)
        w = _KIND_WEIGHT.get(r["kind"], 1.0)
        if w > 0:                       # responsibilities (w=0) are not scored as gaps
            w_tot += w
            if hit:
                w_cov += w
        (covered if hit else missing).append(r)

    # weighted keyword ratio (fallback / blend)
    kw_ratio = (w_cov / w_tot) if w_tot else None

    pe = profile_vec if profile_vec is not None else embed(profile_text)
    se = posting_vec if posting_vec is not None else embed(posting_text)
    sem_pct = semantic_pct(pe, se)
    return round(blend(sem_pct, kw_ratio) * 100), covered, missing


def semantic_pct(profile_vec, posting_vec) -> float | None:
    """Cosine similarity rescaled from E5's typical 0.6..0.95 band to 0..1 (None w/o vectors)."""
    if profile_vec is None or posting_vec is None:
        return None
    sem = _cosine(profile_vec, posting_vec)
    return max(0.0, min(1.0, (sem - 0.6) / 0.35))


def blend(sem_pct: float | None, kw_ratio: float | None) -> float:
    """The one scoring formula — also used by the LLM verification pass when it recomputes
    a score from corrected coverage, so the two can never drift apart.
    Coverage dominates: E5 similarity gives a high baseline for ANY tech text, which
    inflated scores like '45% with 1 of 26 covered' (owner report). Without requirement
    evidence, similarity alone never claims above 60%."""
    if sem_pct is None:
        return kw_ratio if kw_ratio is not None else 0.0
    if kw_ratio is None:
        return min(sem_pct, 0.60)
    return 0.35 * sem_pct + 0.65 * kw_ratio


def coverage_ratio(requirements_with_hits) -> float | None:
    """Weighted coverage from [({'text','kind'}, hit: bool)] pairs — the verifier's way to
    recompute the ratio after the LLM corrects individual hits."""
    w_cov = w_tot = 0.0
    for r, hit in requirements_with_hits:
        w = _KIND_WEIGHT.get(r.get("kind", "must"), 1.0)
        if w > 0:
            w_tot += w
            if hit:
                w_cov += w
    return (w_cov / w_tot) if w_tot else None
