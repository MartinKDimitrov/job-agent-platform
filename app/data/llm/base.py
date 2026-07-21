"""LLM provider contract + registry (BYOK — the user's own key pays for generation).

One isolated module per provider (same rule as job-source adapters): gemini.py, groq.py,
ollama.py, each registering itself here. The application layer calls `generate(...)` through
`get_provider(name)` and never knows transport details.

Security invariants:
- API keys are passed per call, never stored on the provider module, never logged, and never
  allowed to leak into error messages (scrubbed defensively).
- All failures raise LLMError with a short, user-readable message.
"""
from __future__ import annotations

from dataclasses import dataclass

GENERATION_TIMEOUT = 90.0   # generation can be slow; bounded so requests can't hang forever


class LLMError(Exception):
    """A readable, user-presentable generation failure ("invalid key", "rate limited"...)."""


@dataclass(frozen=True)
class ProviderInfo:
    name: str            # registry id, e.g. "gemini"
    label: str           # display name, e.g. "Google Gemini"
    needs_key: bool      # Ollama runs locally without one
    default_model: str
    generate: object     # callable(system, prompt, api_key="", model="") -> str


_REGISTRY: dict[str, ProviderInfo] = {}


def register(info: ProviderInfo) -> None:
    _REGISTRY[info.name] = info


def get_provider(name: str) -> ProviderInfo | None:
    return _REGISTRY.get(name)


def list_providers() -> list[ProviderInfo]:
    return list(_REGISTRY.values())


def scrub(text: str, api_key: str) -> str:
    """Make sure an error message can never echo the user's key back."""
    return text.replace(api_key, "***") if api_key else text
