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


# Version stamp for stored posting vectors: bump on ANY change to input construction or
# prefix mode — enrichment then lazily re-embeds affected rows (measured decision, eval v1:
# asymmetric passage:/query: over CLEAN text, semantic weight raised 0.35 -> 0.5).
EMBED_VERSION = "e5-asym-clean-v2"

# Eval-v1 sweep peaked ~0.8 on the small set; 0.5 is the cautious step (config:
# SEMANTIC_WEIGHT) pending more labeled data.
DEFAULT_SEM_WEIGHT = 0.5


def embed(text: str, prefix: str = "query: "):
    m = _get_model()
    if not m:
        return None
    v = m.encode(prefix + (text or ""), normalize_embeddings=True)
    return v


def embed_query(text: str):
    """The PROFILE side (the 'search query' in E5's asymmetric training)."""
    return embed(text, "query: ")


def embed_passage(text: str):
    """The POSTING side (the 'document'). Feed it CLEAN text (title + requirements) —
    raw 7k-char descriptions truncate at E5's 512 tokens exactly where requirements live."""
    return embed(text, "passage: ")


def posting_embed_text(title: str, requirements: list[dict] | None) -> str:
    """The clean embedding input for a posting: role identity + what it actually asks for."""
    parts = [title or ""]
    parts += [r.get("text", "") for r in requirements or []
              if isinstance(r, dict) and r.get("kind") in ("must", "nice", "resp")]
    return "\n".join(p for p in parts if p)


def _cosine(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a), np.asarray(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / denom)


# Weight of each requirement kind in the keyword-coverage ratio. Must-haves dominate the
# score; nice-to-haves nudge it; responsibilities and soft skills (team player, mindset...)
# are kept for context but never scored as gaps.
_KIND_WEIGHT = {"must": 1.0, "nice": 0.4, "resp": 0.0, "soft": 0.0}


def req_weight(r: dict) -> float:
    """Effective weight of one requirement: kind base × annotated importance (1-5, neutral 3).
    'Kotlin ★★★★★' counts ~1.67× a plain must; 'XML ★' counts ~0.33×."""
    base = _KIND_WEIGHT.get(r.get("kind", "must"), 1.0)
    try:
        w = int(r.get("weight", 3))
    except (TypeError, ValueError):
        w = 3
    return base * (min(5, max(1, w)) / 3.0)


# Tokens shared by EVERY tech profile and EVERY tech requirement — a match on one of these
# proves nothing ('5+ years of software development' must not be "covered" by a profile
# that merely contains 'years' and 'software'). Caught by the eval set: a Python profile
# scored 100% coverage on 'Senior Android Developer' through exactly these words.
_GENERIC_REQ_TOKENS = {
    "years", "year", "experience", "experienced", "software", "development", "developer",
    "engineer", "engineering", "team", "teams", "working", "work", "knowledge", "skills",
    "skill", "strong", "good", "excellent", "solid", "ability", "understanding", "using",
    "със", "опит", "години", "умения", "познания", "работа", "the", "and", "with",
}


def requirement_hit(r: dict, profile_text: str, profile_tokens: set[str] | None = None) -> bool:
    """Is this requirement covered by the profile? ANNOTATED requirements match
    deterministically — any canonical skill present in the profile text (word-boundary);
    un-annotated ones fall back to whole-token overlap minus generic tokens."""
    skills = r.get("skills")
    if skills:
        low = (profile_text or "").lower()
        for s in skills:
            if re.search(r"(?<![a-z0-9+#.])" + re.escape(s) + r"(?![a-z0-9+#.])", low):
                return True
        return False
    toks = profile_tokens if profile_tokens is not None else _tokens(profile_text)
    rtok = _tokens(r.get("text", "")) - _GENERIC_REQ_TOKENS
    return bool(rtok and rtok & (toks - _GENERIC_REQ_TOKENS))


def _norm_reqs(requirements) -> list[dict]:
    """Accept either the new [{'text','kind'}] shape or the old [str] one (older rows / callers)
    so scoring never breaks on legacy data."""
    norm = []
    for r in requirements or []:
        if isinstance(r, dict):
            # keep ALL keys (annotation adds skills/weight) — only default the core two
            norm.append({**r, "text": r.get("text", ""), "kind": r.get("kind", "must")})
        else:
            norm.append({"text": str(r), "kind": "must"})
    return norm


def score(profile_text: str, posting_text: str, requirements=None,
          profile_vec=None, posting_vec=None, sem_weight: float = DEFAULT_SEM_WEIGHT):
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
        hit = requirement_hit(r, profile_text, p_tok)
        w = req_weight(r)
        if w > 0:                       # responsibilities/soft (w=0) are not scored as gaps
            w_tot += w
            if hit:
                w_cov += w
        (covered if hit else missing).append(r)

    # weighted keyword ratio (fallback / blend)
    kw_ratio = (w_cov / w_tot) if w_tot else None

    pe = profile_vec if profile_vec is not None else embed_query(profile_text)
    se = posting_vec if posting_vec is not None else embed_passage(posting_text)
    sem_pct = semantic_pct(pe, se)
    return round(blend(sem_pct, kw_ratio, sem_weight) * 100), covered, missing


def semantic_pct(profile_vec, posting_vec) -> float | None:
    """Cosine similarity rescaled from E5's typical 0.6..0.95 band to 0..1 (None w/o vectors)."""
    if profile_vec is None or posting_vec is None:
        return None
    sem = _cosine(profile_vec, posting_vec)
    return max(0.0, min(1.0, (sem - 0.6) / 0.35))


def blend(sem_pct: float | None, kw_ratio: float | None,
          sem_weight: float = DEFAULT_SEM_WEIGHT) -> float:
    """The one scoring formula — also used by the LLM verification pass when it recomputes
    a score from corrected coverage, so the two can never drift apart. `sem_weight` comes
    from config at the call sites (domain stays dependency-free). Without requirement
    evidence, similarity alone never claims above 60%."""
    if sem_pct is None:
        return kw_ratio if kw_ratio is not None else 0.0
    if kw_ratio is None:
        return min(sem_pct, 0.60)
    return sem_weight * sem_pct + (1 - sem_weight) * kw_ratio


def coverage_ratio(requirements_with_hits) -> float | None:
    """Weighted coverage from [({'text','kind',...}, hit: bool)] pairs — the verifier's way
    to recompute the ratio after the LLM corrects individual hits."""
    w_cov = w_tot = 0.0
    for r, hit in requirements_with_hits:
        w = req_weight(r)
        if w > 0:
            w_tot += w
            if hit:
                w_cov += w
    return (w_cov / w_tot) if w_tot else None
