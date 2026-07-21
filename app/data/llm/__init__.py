"""BYOK LLM providers — one isolated module per provider (CLAUDE.md §5 isolation rule).
Importing this package registers all built-in providers."""
from .base import LLMError, ProviderInfo, get_provider, list_providers, register  # noqa: F401
from . import gemini  # noqa: F401  (registers "gemini")
from . import groq    # noqa: F401  (registers "groq")
from . import ollama  # noqa: F401  (registers "ollama")
