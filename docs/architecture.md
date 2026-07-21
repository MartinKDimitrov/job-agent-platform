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
| **core** | `app/core/` | `config.py` — pydantic settings (env-driven) | — |
| **domain** | `app/domain/` | Pure business logic: `entities.py` (RawPosting), `scoring.py` (E5 embeddings + weighted keyword match), `extraction.py` (JD → must/nice/resp requirements), `filters.py` (seniority/location hard filters), `dedup.py` (cross-source dedup normalization), `taxonomy.py` (occupation → skills), `activity_rules.py` (who gets searched), `text.py` (HTML→text) | nothing (stdlib + optional ML libs only) |
| **data** | `app/data/` | I/O: `db.py` (engine/session), `models.py` (SQLAlchemy ORM), `security.py` (bcrypt+JWT), `mailer.py` (SMTP w/ dev-log fallback), `ingest.py` (posting persistence + dedup application), `activity_repo.py`, `metrics_repo.py`, `seed_sources.py`, **`sources/`** — one isolated adapter per job source (greenhouse, lever, ashby, dev_bg, jobtiger, remoteok, wwr) behind a tiny registry (`sources/base.py`) and shared HTTP helpers (`sources/http.py`) | domain, core |
| **application** | `app/application/` | Use cases: `usecases/search.py` (fetch → prefilter → ingest → hard-filter → extract → score → Match), `usecases/digest.py` (daily run over all active users + email digest), `run_stats.py` (per-run metrics collector) | domain, data, core |
| **presentation** | `app/presentation/` | HTTP/UI: `web.py` (HTML shell: header, user menu, SVG icons), `static/design.css` (the Lovable-produced design system, served at /static), `seo.py` (meta/OG/JSON-LD), `i18n.py` (BG/EN), `routers/` (auth, profiles, onboarding, account, sources, seo, documents) | all layers |

**Entrypoints (composition roots):**
- `app/main.py` — FastAPI app (web server).
- `app/jobs.py` — `python -m app.jobs` — daily digest (cron).
- `app/metrics.py` — `python -m app.metrics` — crawl-run metrics report.

**Rules**
1. `domain` never imports from `data`, `application`, or `presentation`.
2. One **isolated adapter per job source** (`data/sources/<source>.py`) with its own tests —
   a change to one source can never break another. The pipeline consumes only the normalized
   `domain.entities.RawPosting`.
3. Every module ships hermetic pytest tests (`tests/`, temp SQLite, no network).
4. Docs in `docs/` are updated in the same change that alters behaviour.

**Testing:** `pytest` (135+ tests). `tests/conftest.py` overrides `DATABASE_URL` to a temp
SQLite file, forces the keyword-scoring path (no model download), and clears OAuth env vars.

**Frontend note:** the app is server-rendered (SEO-first); there is no client state, so no
client-state pattern (MVI/Redux) applies yet. When the Phase 4 frontend (Lovable/React)
arrives, MVI-style unidirectional state management becomes relevant **there**.
