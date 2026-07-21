"""Groq provider (fast + free tier; OpenAI-compatible chat completions API)."""
from __future__ import annotations

import httpx

from .base import GENERATION_TIMEOUT, LLMError, ProviderInfo, register, scrub

API = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"


def generate(system: str, prompt: str, api_key: str = "", model: str = "") -> str:
    if not api_key:
        raise LLMError("Groq requires an API key (console.groq.com → API Keys).")
    body = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
    }
    try:
        r = httpx.post(API, json=body, headers={"Authorization": f"Bearer {api_key}"},
                       timeout=GENERATION_TIMEOUT)
    except httpx.HTTPError as e:
        raise LLMError(scrub(f"Groq request failed: {e}", api_key)) from e
    if r.status_code in (401, 403):
        raise LLMError("Groq rejected the API key — check it in your account settings.")
    if r.status_code == 429:
        raise LLMError("Groq rate limit reached — try again in a minute.")
    if r.status_code != 200:
        raise LLMError(scrub(f"Groq error {r.status_code}: {r.text[:200]}", api_key))
    try:
        return r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise LLMError("Groq returned an unexpected response shape.") from e


register(ProviderInfo(name="groq", label="Groq", needs_key=True,
                      default_model=DEFAULT_MODEL, generate=generate))
