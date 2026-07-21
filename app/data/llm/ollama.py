"""Ollama provider — a local model, no API key, fully free. On the user's machine during
development; on our VPS for the no-key fallback tier (ROADMAP step 24)."""
from __future__ import annotations

import httpx

from .base import GENERATION_TIMEOUT, LLMError, ProviderInfo, register

API = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3.1"


def generate(system: str, prompt: str, api_key: str = "", model: str = "") -> str:
    body = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "stream": False,
    }
    try:
        r = httpx.post(API, json=body, timeout=GENERATION_TIMEOUT)
    except httpx.HTTPError as e:
        raise LLMError(f"Ollama is not reachable at localhost:11434 — is it running? ({e})") from e
    if r.status_code == 404:
        raise LLMError(f"Ollama model not found — run: ollama pull {model or DEFAULT_MODEL}")
    if r.status_code != 200:
        raise LLMError(f"Ollama error {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["message"]["content"]
    except (KeyError, ValueError) as e:
        raise LLMError("Ollama returned an unexpected response shape.") from e


register(ProviderInfo(name="ollama", label="Ollama (local)", needs_key=False,
                      default_model=DEFAULT_MODEL, generate=generate))
