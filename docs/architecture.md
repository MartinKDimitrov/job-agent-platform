# Architecture

The codebase follows **Clean Architecture** with four layers. Dependencies point **inward**
(toward `domain`); the domain knows nothing about frameworks, databases, or HTTP.

```
presentation ──▶ application ──▶ domain ◀── data
      │               │                      ▲
      └───────────────┴──────────────────────┘   (presentation/application may use data)
core (config) is available to all outer layers; domain stays dependency-free.
```

| Layer | Path | Contents | May import |
|---|---|---|---|
| **core** | `app/core/` | `config.py` — pydantic settings (env-driven: ingest interval, age/probe/verify budgets, server LLM lane) | — |
| **domain** | `app/domain/` | Pure business logic: `entities.py` (RawPosting), `scoring.py` (blend/coverage/semantic — ONE scoring formula), `extraction.py` (JD → must/nice/resp/soft), `filters.py` (seniority/location/geo hard filters), `dedup.py`, `taxonomy.py`, `activity_rules.py`, `text.py`, `prompts/` (versioned LLM prompts: documents v2, verify v1) | nothing (stdlib + optional ML libs only) |
| **data** | `app/data/` | I/O: `db.py`, `models.py` (User, Profile, Posting, Match, Company, Document, CrawlRun…), `security.py`, `mailer.py`, `ingest.py` (persistence + dedup + liveness touch), `keystore.py` (Fernet-encrypted BYOK keys), `activity_repo.py`, `metrics_repo.py`, `company_repo.py`, `ats_detect.py` (ATS auto-detection + careers finder), `seed_sources.py`, `companies_bg.py` (multi-industry seed), `llm/` (gemini/groq/ollama providers), **`sources/`** — one isolated adapter per platform (greenhouse, lever, ashby, workable, smartrecruiters, recruitee, personio, teamtailor, jsonld_careers, dev_bg, jobtiger, remoteok, wwr) + `http.py` (shared HTTP, 429 backoff) | domain, core |
| **application** | `app/application/` | Use cases: `usecases/search.py` (ingest_from_sources = write side; search_db = read side; hygiene: age/takedown/URL-probe), `usecases/ingest_job.py` (scheduled ingest + in-app daemon thread), `usecases/verify_coverage.py` (LLM verification), `usecases/generate_document.py` (BYOK/free-lane CV & letters), `usecases/digest.py`, `run_stats.py` | domain, data, core |
| **presentation** | `app/presentation/` | HTTP/UI: `web.py` (shell: menu, icons, loading overlay, ripple), `static/design.css`, `seo.py`, `i18n.py` (full BG/EN incl. logged-in app + digest email), `doc_template.py` (A4 print), `routers/` (auth, profiles, onboarding, account, sources, seo, documents, jobs_public) | all layers |

**Entrypoints (composition roots):**
- `app/main.py` — FastAPI app (web server; starts the background ingester when
  `INGEST_EVERY_HOURS` > 0).
- `app/jobs.py` — `python -m app.jobs` (daily digest) / `python -m app.jobs ingest` (cron).
- `app/metrics.py` — `python -m app.metrics` — crawl-run metrics report.
- `app/tools/` — registry CLIs: `detect_companies`, `find_careers`, `probe_jsonld`.

**Rules**
1. `domain` never imports from `data`, `application`, or `presentation`.
2. One **isolated adapter per job source** (`data/sources/<source>.py`) with its own tests —
   a change to one source can never break another. The pipeline consumes only the normalized
   `domain.entities.RawPosting`.
3. Every module ships hermetic pytest tests (`tests/`, temp SQLite, no network).
4. Docs in `docs/` are updated in the same change that alters behaviour.

**Testing:** `pytest` (296 tests). `tests/conftest.py` overrides `DATABASE_URL` to a temp
SQLite file, forces the keyword-scoring path (no model download), clears OAuth env vars, and
forces OFF everything that would touch the real network from a local `.env`: the background
ingester (`INGEST_EVERY_HOURS=0`), the takedown URL probe (`TAKEDOWN_PROBE_BUDGET=0`) and
the platform LLM lane (`SERVER_LLM_PROVIDER=`).

**Frontend note:** the app is server-rendered (SEO-first); there is no client state, so no
client-state pattern (MVI/Redux) applies yet. When the Phase 4 frontend (Lovable/React)
arrives, MVI-style unidirectional state management becomes relevant **there**.
