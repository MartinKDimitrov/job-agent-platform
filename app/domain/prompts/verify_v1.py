"""Coverage-verification prompt v1 (approved 2026-07-22): a cheap LLM double-checks the
token-based covered/missing split — 'api' in the profile does NOT cover 'GraphQL APIs',
'English A2' does not cover 'fluent English'. The model only re-labels; scores are
recomputed by domain.scoring.blend so the formula can't drift.

Contract: numbered requirements in, STRICT JSON out ({"covered": [numbers]}). Anything
unparseable means 'leave the match untouched' — verification is always best-effort.
"""
from __future__ import annotations

import json
import re

VERIFY_VERSION = "verify-v1"

_SYSTEM = (
    "You are a careful technical recruiter. The candidate's profile lists their skills and "
    "experience — treat every listed skill as TRUE; do not demand extra proof. For each "
    "numbered job requirement decide whether the profile MATCHES it:\n"
    "- covered: a listed skill or the described experience clearly satisfies it (a 'Kotlin' "
    "skill covers 'experience building Android apps with Kotlin'; the target role plus its "
    "core skills cover generic requirements of that role);\n"
    "- NOT covered: the requirement demands a DIFFERENT technology, level or domain than the "
    "profile shows — knowing REST does not cover GraphQL, 'English A2' does not cover fluent "
    "English, a generic word overlap alone (e.g. 'api', 'developer') is not a match.\n"
    "Answer ONLY with JSON exactly of the form "
    '{"covered": [<numbers of requirements the profile matches>]} — no other text.')


def build_verify_prompt(profile, requirements: list[dict]) -> tuple[str, str]:
    """(system, user) for the verification call. `requirements` are the scored must/nice
    items in a FIXED order — the answer's numbers index into exactly this list (1-based)."""
    lines = [f"{i + 1}. [{r.get('kind', 'must')}] {r.get('text', '')}"
             for i, r in enumerate(requirements)]
    user = (
        "CANDIDATE PROFILE:\n"
        f"Target roles: {profile.target_roles or '-'}\n"
        f"Skills: {profile.skills or '-'}\n"
        f"Experience: {profile.experience or '-'}\n"
        f"Languages: {profile.languages or '-'} (English level: {profile.english_level or '-'})\n\n"
        "REQUIREMENTS:\n" + "\n".join(lines) + "\n\n"
        'JSON answer ({"covered": [...]}):')
    return _SYSTEM, user


def parse_verify_response(text: str, n_requirements: int) -> set[int] | None:
    """0-based indices of covered requirements, or None when the answer is unusable."""
    m = re.search(r"\{[^{}]*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    nums = data.get("covered")
    if not isinstance(nums, list):
        return None
    out = set()
    for x in nums:
        if isinstance(x, (int, float)) and 1 <= int(x) <= n_requirements:
            out.add(int(x) - 1)
    return out
