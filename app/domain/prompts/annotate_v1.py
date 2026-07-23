"""Requirement annotation prompt v1 (approved 2026-07-23): one LLM call per POSTING turns
each must/nice requirement into user-independent knowledge — the canonical skills that
satisfy it (each listed skill ALONE suffices) and its importance in THIS posting (1-5).
Per-user coverage then becomes a deterministic set intersection: instant, identical for
every user with similar qualifications, zero LLM on the search path.

Versioned like every prompt here: bump ANNOTATE_VERSION → affected postings lazily
re-annotate on their next ingest touch (annotation_fp guards against text changes).
"""
from __future__ import annotations

import hashlib
import json
import re

ANNOTATE_VERSION = "annotate-v1"

_SCORED_KINDS = ("must", "nice")

_SYSTEM = (
    "You are a technical recruiter building a skills index. For EACH numbered job "
    "requirement, output:\n"
    "- skills: canonical lowercase skill names such that having ANY ONE of them satisfies "
    "the requirement (e.g. 'native Android development with Kotlin or Java' -> "
    '["kotlin", "java"]; \'experience with Kubernetes\' -> ["kubernetes"]). Use short '
    "canonical names (kubernetes, not k8s; javascript, not js). For requirements that are "
    "not about a nameable skill (e.g. 'degree in computer science'), use a short canonical "
    "phrase (\"computer science degree\").\n"
    "- weight: how important this requirement is IN THIS POSTING, 1 (peripheral) to 5 "
    "(core of the role).\n"
    "Answer ONLY with JSON exactly of the form "
    '{"annotations": [{"n": 1, "skills": [...], "weight": 3}, ...]} — one entry per '
    "requirement, no other text.")


def scored_requirements(requirements: list[dict] | None) -> list[dict]:
    return [r for r in requirements or []
            if isinstance(r, dict) and r.get("kind", "must") in _SCORED_KINDS]


def requirements_fingerprint(requirements: list[dict] | None) -> str:
    """Stable fingerprint of the must/nice texts — annotation is invalid when it changes."""
    texts = "\n".join(r.get("text", "") for r in scored_requirements(requirements))
    return hashlib.sha256(texts.encode("utf-8")).hexdigest()[:64]


def build_annotate_prompt(title: str, requirements: list[dict]) -> tuple[str, str]:
    lines = [f"{i + 1}. {r.get('text', '')}" for i, r in enumerate(requirements)]
    user = (f"JOB TITLE: {title}\n\nREQUIREMENTS:\n" + "\n".join(lines)
            + '\n\nJSON answer ({"annotations": [...]}):')
    return _SYSTEM, user


def parse_annotate_response(text: str, n_requirements: int) -> dict[int, tuple[list[str], int]] | None:
    """{0-based index: (skills, weight)} or None when unusable. Partial answers are fine —
    unlisted requirements simply stay un-annotated."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    items = data.get("annotations")
    if not isinstance(items, list):
        return None
    out: dict[int, tuple[list[str], int]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        n = it.get("n")
        skills = it.get("skills")
        if not (isinstance(n, (int, float)) and 1 <= int(n) <= n_requirements):
            continue
        if not (isinstance(skills, list) and all(isinstance(s, str) for s in skills)):
            continue
        try:
            weight = min(5, max(1, int(it.get("weight", 3))))
        except (TypeError, ValueError):
            weight = 3
        cleaned = [s.strip().lower() for s in skills if s.strip()]
        if cleaned:
            out[int(n) - 1] = (cleaned[:8], weight)
    return out or None
