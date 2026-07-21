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
# score; nice-to-haves nudge it; responsibilities are shown for context but not scored as gaps.
_KIND_WEIGHT = {"must": 1.0, "nice": 0.4, "resp": 0.0}


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


def score(profile_text: str, posting_text: str, requirements=None):
    """Return (score_0_100, covered[list[dict]], missing[list[dict]]).

    - Semantic similarity via E5 (if available) drives the base score.
    - Weighted keyword coverage (must-have > nice-to-have) gives covered/missing and a
      fallback score when embeddings are unavailable. Each covered/missing entry keeps its
      {'text','kind'} so the UI can show *why* a posting scored the way it did.
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

    pe, se = embed(profile_text), embed(posting_text)
    if pe is not None and se is not None:
        sem = _cosine(pe, se)          # ~0..1 for E5 normalized
        sem_pct = max(0.0, min(1.0, (sem - 0.6) / 0.35))  # rescale typical 0.6..0.95 band
        base = sem_pct if kw_ratio is None else 0.6 * sem_pct + 0.4 * kw_ratio
    else:
        base = kw_ratio if kw_ratio is not None else 0.0

    return round(base * 100), covered, missing
