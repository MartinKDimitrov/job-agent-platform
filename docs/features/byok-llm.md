# BYOK LLM (CV & Cover-letter Generation) — Phase 3

**What it does (so far — step 3.1):** a provider layer for BYOK generation. The user's own
API key pays for generative calls (see `LLM_COST_STRATEGY.md` — the platform's core stays
LLM-free). One isolated module per provider behind a single contract:

| Provider | Module | Key | Default model |
|---|---|---|---|
| Google Gemini | `data/llm/gemini.py` | required (free tier at aistudio.google.com) | `gemini-2.5-flash` |
| Groq | `data/llm/groq.py` | required (free tier at console.groq.com) | `llama-3.3-70b-versatile` |
| Ollama (local) | `data/llm/ollama.py` | none — localhost:11434 | `llama3.1` |

**Contract** (`data/llm/base.py`): `generate(system, prompt, api_key="", model="") -> str`,
raising `LLMError` with a short user-readable message on any failure. Security invariants:
keys are passed per call, never stored on modules, never logged, and scrubbed from error
text defensively. Registry: `get_provider(name)` / `list_providers()`.

**BYOK settings (step 3.2):** the Account page has an "AI generation" card — pick a provider,
paste a key, **Test & save** runs a tiny real call first; a key that fails the test is never
stored. Keys are encrypted at rest (Fernet, key derived from the app `SECRET_KEY` —
`data/keystore.py`, table `UserLLMConfig`), never rendered back to the browser, never logged,
and removable any time. Keyless providers (Ollama) skip the key requirement.

**Coming next:** 3.3 versioned prompts + the generation use case (CEFR-aware, no invented
skills); 3.4 document storage + .docx download; 3.5 server-side Ollama fallback with daily
limits (deploy phase).

**Tests:** `tests/test_llm_providers.py`, `tests/test_byok_settings.py`.
