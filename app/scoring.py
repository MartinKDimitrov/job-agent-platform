"""Match scoring via E5 embeddings (local, cheap) with a keyword fallback.

The heavy generative LLM is NOT used here — scoring is embeddings + keyword overlap,
which is near-zero cost and runs locally. See LLM_COST_STRATEGY.md.
"""
import re
from functools import lru_cache

from .config import settings

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


def score(profile_text: str, posting_text: str, requirements: list[str] | None = None):
    """Return (score_0_100, covered[list], missing[list]).

    - Semantic similarity via E5 (if available) drives the base score.
    - Keyword overlap on the profile's skills vs the posting gives covered/missing
      and a fallback score when embeddings are unavailable.
    """
    requirements = requirements or []
    p_tok = _tokens(profile_text)
    covered, missing = [], []
    for req in requirements:
        rtok = _tokens(req)
        if rtok and rtok & p_tok:
            covered.append(req)
        else:
            missing.append(req)

    # keyword-based ratio (fallback / blend)
    kw_ratio = len(covered) / len(requirements) if requirements else None

    pe, se = embed(profile_text), embed(posting_text)
    if pe is not None and se is not None:
        sem = _cosine(pe, se)          # ~0..1 for E5 normalized
        sem_pct = max(0.0, min(1.0, (sem - 0.6) / 0.35))  # rescale typical 0.6..0.95 band
        base = sem_pct if kw_ratio is None else 0.6 * sem_pct + 0.4 * kw_ratio
    else:
        base = kw_ratio if kw_ratio is not None else 0.0

    return round(base * 100), covered, missing
