"""Versioned prompt templates for document generation (CLAUDE.md §8 conventions).

All prompts live here — in one place, versioned — so they can be evaluated and improved
deliberately rather than scattered inline. Current version: v1.
"""
from .documents_v1 import PROMPT_VERSION, build_cv_prompt, build_cover_letter_prompt  # noqa: F401
