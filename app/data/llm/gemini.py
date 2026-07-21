"""Google Gemini provider (recommended BYOK start — free API tier at aistudio.google.com).

REST generateContent endpoint; the key travels in the X-goog-api-key header (not the URL, so
it can't end up in access logs)."""
from __future__ import annotations

import httpx

from .base import GENERATION_TIMEOUT, LLMError, ProviderInfo, register, scrub

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# The -latest alias always points to the current flash model, so a retired model id can never
# break generation again (gemini-2.5-flash got retired for new users and 404'd us).
DEFAULT_MODEL = "gemini-flash-latest"


def generate(system: str, prompt: str, api_key: str = "", model: str = "") -> str:
    if not api_key:
        raise LLMError("Gemini requires an API key (aistudio.google.com → Get API key).")
    model = model or DEFAULT_MODEL
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    try:
        r = httpx.post(API.format(model=model), json=body,
                       headers={"X-goog-api-key": api_key}, timeout=GENERATION_TIMEOUT)
    except httpx.TimeoutException as e:
        raise LLMError("Gemini took too long to respond (free-tier congestion happens) — "
                       "please try again.") from e
    except httpx.HTTPError as e:
        raise LLMError(scrub(f"Gemini request failed: {e}", api_key)) from e
    if r.status_code in (401, 403):
        raise LLMError("Gemini rejected the API key — check it in your account settings.")
    if r.status_code == 429:
        raise LLMError("Gemini rate limit reached — try again in a minute.")
    if r.status_code == 404:
        raise LLMError(f"Gemini model '{model}' not found or retired — leave Model empty to use "
                       f"the latest, or pick one from ai.google.dev/gemini-api/docs/models.")
    if r.status_code != 200:
        raise LLMError(scrub(f"Gemini error {r.status_code}: {r.text[:200]}", api_key))
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError) as e:
        raise LLMError("Gemini returned an unexpected response shape.") from e


register(ProviderInfo(name="gemini", label="Google Gemini", needs_key=True,
                      default_model=DEFAULT_MODEL, generate=generate))
