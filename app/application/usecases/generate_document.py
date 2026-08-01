"""Generate a CV or cover letter for a (profile, posting) pair using the user's BYOK LLM.

The expensive generative call runs on the user's own key (LLM_COST_STRATEGY): we load their
provider config, build the versioned prompt from STRUCTURED data (profile + extracted
requirements + covered/missing from the match), call the provider, and store the result as a
Document. The user reviews/edits before using it — human in the loop, always.
"""
from __future__ import annotations

from datetime import datetime, time as dtime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import settings
from ...data.models import Profile, Posting, Match, Document
from ...data.keystore import get_config
from ...data.llm import LLMError, get_provider
from ...domain.prompts import PROMPT_VERSION, build_cv_prompt, build_cover_letter_prompt

KINDS = ("cv", "cover_letter")
LANGS = ("en", "bg")


class GenerationError(Exception):
    """User-presentable failure (bad posting, provider error, daily limit...)."""


class NoProviderConfigured(GenerationError):
    """No BYOK key AND no server free lane — the route sends the user to Account."""


def _resolve_llm(db: Session, user) -> tuple[dict, bool]:
    """(provider config, is_free_lane). BYOK wins (unlimited, user's own account); else the
    platform's shared provider with a daily cap; else there is nothing to generate with."""
    cfg = get_config(db, user.id)
    if cfg is not None:
        return cfg, False
    if settings.server_llm_provider:
        today = datetime.combine(datetime.utcnow().date(), dtime.min)
        used = db.execute(select(func.count(Document.id)).where(
            Document.user_id == user.id, Document.created_at >= today)).scalar() or 0
        if used >= settings.free_docs_per_day:
            raise GenerationError(
                f"Daily free limit reached ({settings.free_docs_per_day}/day). "
                "Add your own AI key in Account for unlimited generation.")
        return {"provider": settings.server_llm_provider,
                "api_key": settings.server_llm_api_key,
                "model": settings.server_llm_model}, True
    raise NoProviderConfigured(
        "No AI provider configured — add your key in Account → AI generation.")


def generate_document(db: Session, user, profile_id: int, posting_id: int,
                      kind: str = "cv", lang: str = "en") -> Document:
    if kind not in KINDS or lang not in LANGS:
        raise GenerationError("Unknown document kind or language.")
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise GenerationError("Profile not found.")
    posting = db.get(Posting, posting_id)
    if posting is None:
        raise GenerationError("Posting not found.")

    cfg, _free_lane = _resolve_llm(db, user)
    provider = get_provider(cfg["provider"])
    if provider is None:
        raise GenerationError("Configured provider is no longer available — re-add it in Account.")

    match = db.execute(select(Match).where(
        Match.profile_id == profile.id, Match.posting_id == posting.id)).scalar_one_or_none()
    covered = match.covered if match else None
    missing = match.missing if match else None

    build = build_cv_prompt if kind == "cv" else build_cover_letter_prompt
    # for Bulgarian documents, feed the official ПОО competencies for the profession as reference
    # vocabulary (never new skills) so the wording is authentic — see build_cv_prompt._napoo_block
    napoo = []
    if lang == "bg" and (getattr(profile, "napoo_direction", "") or getattr(profile, "vertical", "")):
        from ...data.taxonomy_repo import napoo_skills_for_profile
        napoo = napoo_skills_for_profile(db, profile, 25)
    system, prompt = build(profile, posting, covered, missing, lang=lang, napoo=napoo)
    try:
        content = provider.generate(system, prompt, api_key=cfg["api_key"], model=cfg["model"])
    except LLMError as e:
        raise GenerationError(str(e)) from e

    doc = Document(user_id=user.id, posting_id=posting.id, kind=kind, lang=lang,
                   content=content.strip(), provider=cfg["provider"],
                   model=cfg["model"] or provider.default_model,
                   prompt_version=PROMPT_VERSION)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc
