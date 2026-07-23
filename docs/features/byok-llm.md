# BYOK LLM (CV & Cover-letter Generation) — Phase 3

**What it does (so far — step 3.1):** a provider layer for BYOK generation. The user's own
API key pays for generative calls (see `LLM_COST_STRATEGY.md` — the platform's core stays
LLM-free). One isolated module per provider behind a single contract:

| Provider | Module | Key | Default model |
|---|---|---|---|
| Google Gemini | `data/llm/gemini.py` | required (free tier at aistudio.google.com) | `gemini-flash-latest` (alias — always the current flash model) |
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

**Generation (step 3.3):** every match row has **CV** and **Letter** buttons. The use case
(`application/usecases/generate_document.py`) loads the user's BYOK config, builds a
**versioned prompt** (`domain/prompts/documents_v1.py`) from STRUCTURED data — profile fields,
extracted must/nice requirements, covered/missing from the match (never whole pages; tokens
are the user's money) — calls the provider, and stores a `Document` (kind, lang en/bg,
provider/model, prompt_version). Prompt constraints: mid-register tone, the candidate's CEFR
English level, and the hard honesty rule — never invent skills/experience; missing
requirements are listed explicitly as "do NOT claim these". The document view says plainly:
review and edit before using (human in the loop). Failures (no key configured, provider
errors) surface as readable banners, never 500s.

**PDF & design (step 3.4):** the document view has **⬇ Download PDF** — it opens
`/documents/{id}/print`, a standalone A4 view of the **Lovable-designed template**
(`presentation/doc_template.py`; Lovable project 038dd6c8): navy accent matching the app,
system fonts (Cyrillic-safe), ATS-friendly, print button hidden in print, `noindex`. The
browser's print dialog saves the styled PDF; at deploy time the same template gets a
server-side renderer (weasyprint) for one-click downloads. Regenerate controls (other
language EN↔BG, other kind CV↔Letter) resolve the profile via the Match table.

**Free lane (shipped):** users WITHOUT a key generate through the platform's shared provider
(`SERVER_LLM_PROVIDER/_API_KEY/_MODEL` env — groq free tier now, ollama at deploy), capped at
`FREE_DOCS_PER_DAY` (3) per user; hitting the cap explains itself and points to BYOK.
With neither key nor lane, the CV/Letter buttons land on Account with an ask-for-key banner
at exactly the moment the key is needed. BYOK users stay unlimited on their own provider.

**Coverage verification (shipped):** the same provider chain powers the match verification
pass (verify-v1, no doc-quota use) — see search-and-scoring.md.

**Coming next:** requirement skill-annotation at ingest (one LLM call per POSTING, shared by
all users — approved 2026-07-23); server-side PDF rendering at deploy; prompt eval harness.

**Tests:** `tests/test_llm_providers.py`, `tests/test_byok_settings.py`, `tests/test_generate.py`.
