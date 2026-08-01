"""Prompt templates v2 for CV and cover-letter generation.

v2 (over v1): hard skills whitelist. Real-world v1 output blended a skill from the JOB TITLE
("Machine Learning") into Key Skills for a candidate whose profile had no such skill — the
generic "never invent" rule was not enough. v2 makes the skills rule surgical: the Key Skills
section may contain ONLY items copied from the candidate's skills list, verbatim.

Conventions (CLAUDE.md §8 / LLM_COST_STRATEGY):
- Pass STRUCTURED data (profile fields + extracted requirements), never whole pages — token
  cost is the user's money (BYOK).
- Explicit constraints: mid-register tone, the candidate's CEFR English level (the text must
  read like them), and the hard honesty rule — never invent skills/experience; omissions are
  better than fabrications ("unknown" is allowed).
- Output language is a parameter (en/bg) — the product promise is BG + EN documents.
"""
from __future__ import annotations

PROMPT_VERSION = "v2"

_LANG_NAMES = {"en": "English", "bg": "Bulgarian"}
_DESCRIPTION_CAP = 800   # chars of raw JD passed for context — requirements carry the substance


def _req_lines(requirements: list | None, kind: str) -> str:
    out = []
    for r in requirements or []:
        text = r.get("text", "") if isinstance(r, dict) else str(r)
        rkind = r.get("kind", "must") if isinstance(r, dict) else "must"
        if rkind == kind and text:
            out.append(f"- {text}")
    return "\n".join(out) or "- (none listed)"


def _profile_block(profile) -> str:
    return (
        f"Name: {getattr(profile, 'display_name', '') or '(use a neutral header without a name)'}\n"
        f"Target roles: {profile.target_roles or '(not specified)'}\n"
        f"Skills: {profile.skills or '(not specified)'}\n"
        f"Experience: {profile.experience or '(not specified)'}\n"
        f"Languages: {profile.languages or '(not specified)'}\n"
        f"English level (CEFR): {profile.english_level or 'B2'}\n"
        f"Location: {profile.location_pref or '(not specified)'}"
    )


def _job_block(posting, covered=None, missing=None) -> str:
    desc = (posting.description or "")[:_DESCRIPTION_CAP]
    covered_txt = ", ".join(
        (c.get("text", "") if isinstance(c, dict) else str(c)) for c in (covered or [])[:12]
    ) or "(unknown)"
    missing_txt = ", ".join(
        (m.get("text", "") if isinstance(m, dict) else str(m)) for m in (missing or [])[:8]
    ) or "(none identified)"
    return (
        f"Job title: {posting.title}\nCompany: {posting.company}\n"
        f"Location: {posting.location or '(not specified)'}\n"
        f"Must-have requirements:\n{_req_lines(posting.requirements, 'must')}\n"
        f"Nice-to-have:\n{_req_lines(posting.requirements, 'nice')}\n"
        f"Requirements the candidate covers: {covered_txt}\n"
        f"Requirements the candidate does NOT cover (be honest, never claim these): {missing_txt}\n"
        f"Job description excerpt:\n{desc}"
    )


def _system(lang: str, cefr: str) -> str:
    return (
        f"You are an expert career-document writer. Write in {_LANG_NAMES.get(lang, 'English')}. "
        f"The candidate's English level is {cefr} (CEFR); when writing in English, keep vocabulary "
        f"and sentence complexity at that level so the text reads authentically like the candidate. "
        "Tone: mid-register — professional but not stiff, never chatty. "
        "STRICT RULES: use ONLY facts provided in the candidate profile. Never invent skills, "
        "employers, dates, numbers, or experience. If relevant information is missing, omit it "
        "rather than guessing. It is acceptable to leave a gap unaddressed; a fabricated claim "
        "is not. SKILLS WHITELIST: any skill, technology or competence you mention must appear "
        "verbatim in the candidate's Skills or Experience fields — never import skills from the "
        "job title or the job requirements. If the job demands a skill the candidate does not "
        "list, leave it out entirely. Output plain text without markdown syntax."
    )


def _napoo_block(napoo) -> str:
    """Official Bulgarian ПОО competencies for the profession — REFERENCE vocabulary, never new
    skills: it lets the model phrase the candidate's real skills in authentic official terms."""
    if not napoo:
        return ""
    return ("\n\nOFFICIAL COMPETENCIES FOR THIS PROFESSION (НАПОО — reference vocabulary ONLY: use "
            "this official Bulgarian phrasing to describe the candidate's ACTUAL skills more "
            "professionally; NEVER claim a competency the candidate does not already have):\n- "
            + "\n- ".join(napoo[:25]))


def build_cv_prompt(profile, posting, covered=None, missing=None, lang: str = "en",
                    napoo=None) -> tuple[str, str]:
    """Return (system, user) for a one-page CV tailored to the posting."""
    system = _system(lang, profile.english_level or "B2")
    user = (
        "CANDIDATE PROFILE:\n" + _profile_block(profile) +
        "\n\nTARGET JOB:\n" + _job_block(posting, covered, missing) +
        _napoo_block(napoo) +
        "\n\nTASK: Write a one-page CV tailored to this job. Lead with what the job requires "
        "and the candidate actually has. Sections (include only those with data): Professional "
        "Summary (3-4 lines), Key Skills (grouped, most relevant first), Experience, Languages. "
        "The Key Skills section may contain ONLY items copied verbatim from the candidate's "
        "Skills field above — nothing from the job title or requirements that is not also "
        "there. Do not add references, photos, or addresses."
    )
    return system, user


def build_cover_letter_prompt(profile, posting, covered=None, missing=None,
                              lang: str = "en", napoo=None) -> tuple[str, str]:
    """Return (system, user) for a short cover letter (200-250 words)."""
    system = _system(lang, profile.english_level or "B2")
    user = (
        "CANDIDATE PROFILE:\n" + _profile_block(profile) +
        "\n\nTARGET JOB:\n" + _job_block(posting, covered, missing) +
        _napoo_block(napoo) +
        "\n\nTASK: Write a cover letter of 200-250 words addressed to the hiring team. "
        "Open with genuine interest in this specific role, connect 2-3 of the candidate's "
        "strongest matching skills (only ones present in their profile) to the job's must-have "
        "requirements, and close with a clear, "
        "modest call to action. If there is an important requirement the candidate does not "
        "cover, you may briefly and positively acknowledge willingness to learn — never claim "
        "experience they lack. No placeholders like [Company] — use the real names provided."
    )
    return system, user
