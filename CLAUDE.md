# Job Agent Platform — context for Claude

Read this first. It carries the state of the project so a new session can continue
without re-deriving anything.

---

## 1. What this is

A **multi-user job-search platform**. A user registers, fills in one or more **search
profiles**, and the system finds open positions across job platforms, scores each one
against the profile (**match %**), shows a ranked list, and gives a **direct Apply link**.
Later it also generates a **tailored CV + cover letter per posting** (BG + EN).

It must work for **any profession**, not only IT.

Design rationale lives in:
- `ARCHITECTURE.md` — agents, data model, per-site adapter strategy, phased plan
- `DECISIONS.md` — confirmed product decisions (v1) + tooling roadmap
- `LLM_COST_STRATEGY.md` — where LLM is/isn't needed, BYOK model, cost control

**Origin:** grew out of `../job-tracker` (a single-user tracker that is still in use for
the owner's own job search — see that project's `CLAUDE.md`).

---

## 2. Current state (Phases 1–3 done + Phase 2 sources expansion; 296 tests)

Working:
- **Auth** — register / login with email + password (bcrypt directly, JWT in an httpOnly cookie).
  **Google OAuth is active and verified working** when `GOOGLE_CLIENT_ID/SECRET` are set in `.env`
  (personal Google Cloud project; Web client; redirect URIs for `localhost:8001` + `127.0.0.1:8001`;
  the owner's email is a **test user** while the consent screen is in Testing). It degrades
  gracefully with a message when unconfigured (e.g. a fresh clone without those secrets).
- **Profiles** — several per user (target roles, skills, experience, languages + CEFR English
  level, location/remote preference, salary, `min_match` threshold, default 65).
- **Sources screen** (`/sources`) — lists built-in platforms and lets the user **add their own**
  platform/link that we don't cover.
- **Scoring** — `app/extraction.py` parses a job description into must/nice/responsibility
  requirements (rules-based, no LLM); `app/scoring.py` computes a match % (must-have weighted
  higher) plus covered/missing. Uses **local E5 embeddings**; falls back to keyword overlap if
  `sentence-transformers` / the model is unavailable.
  - **The real product flow is: the user describes their skills → we find open positions and
    apply links for them** (Phase 2 auto-fetch). The current "paste a JD" screen is a
    **temporary Phase-1 scaffold** to exercise scoring before auto-fetch exists — the extractor
    will then run on the postings *we* fetch, not on anything a user pastes.
- **Apply** — each match row shows an Apply button to the posting/apply URL.
- **Mobile-friendly** — responsive CSS in the shared page shell (tables become cards under
  700px, full-width buttons, 16px inputs to stop iOS zoom).
- **DB** — PostgreSQL. Tables auto-create on startup (`init_db`).

- **DB-first search** — background ingest every 6h (in-app thread / `python -m app.jobs
  ingest`) writes the index (1000+ live postings); "Search now" reads only (sub-second,
  zero network — test-guaranteed). Enrichment at ingest: requirements, E5 vector,
  posted/last-seen bookkeeping; hygiene: >30d age retire, board-unseen takedown (48h),
  budgeted 404 URL probe; matches rejected by newer filters are cleaned retroactively.
- **Sources** — 13 adapters (greenhouse/lever/ashby/workable/smartrecruiters/recruitee/
  personio/teamtailor/jsonld_careers/dev_bg/jobtiger/remoteok/wwr) + company registry
  (165+ BG firms, 19 industries) with ATS auto-detection and careers-page discovery; 429
  backoff in the shared HTTP layer. Full map: docs/features/sources-and-adapters.md.
- **Scoring & filters** — one blend formula (0.35 sem + 0.65 coverage, sem-only cap 60%);
  must/nice/resp/soft extraction (EN+BG, typography/benefit/marketing traps handled);
  hard filters: seniority, location, geo (country + relocate willingness), no-requirements
  rule. LLM coverage verification (verify-v1): top-8/search, cached per match, BYOK→free
  lane→no-op, "✦ AI-checked" chip. Canonical walkthrough: docs/features/matching-pipeline.md.
- **Documents** — BYOK CV/letters (gemini/groq/ollama, encrypted keys) + platform FREE lane
  (`SERVER_LLM_PROVIDER`, 3 docs/day/user) with ask-for-key-on-click UX; editable, A4 print.
- **Digest** — daily, gated (found-job / 5-day inactivity), no re-notification, user's
  language (UserActivity.lang).
- **UI/i18n** — one-page app fully EN/BG (incl. onboarding, documents, account, digest
  email, public SEO pages); ripple, full-screen loading, source badges.

Next: matching plan phases 3-7 (canonical skills dictionary, scoring hardening, hybrid
recall, observability, salary), applications dashboard, ESCO full taxonomy, VPS deploy
(+Alembic, SMTP). Post-launch: recruiter side (employers submit a posting, we send matching
candidates above THEIR threshold; the planned monetization — deliberately after the product
has real candidates; opt-in/GDPR consent is a hard design requirement).

---

## 3. How to run (and the traps we already hit)

The database is the **MystyBag staging Postgres**, reachable only on that VM's localhost,
so a **SSH tunnel is required**.

```bash
# 1. Tunnel (background). Local port 5433 — 5432 is taken by a local Postgres.
ssh -i /Users/mdimitrov/Desktop/key/hetznerKey -f -N \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
    -L 5433:localhost:5432 root@88.99.175.26
nc -zv localhost 5433          # must say "succeeded"

# 2. Run (from the project root, so .env is found)
cd ~/Desktop/Repository/job-agent-platform
source .venv/bin/activate
python -m uvicorn app.main:app --reload --port 8001
```

Open http://127.0.0.1:8001

**Traps, all of which cost us time already:**
- `.env` must point at **5433**, not 5432 — otherwise it hits the local Postgres and you get
  `role "jobagent" does not exist`.
- If the tunnel dies you get `server closed the connection unexpectedly` (or 500s with `Connection refused` on 5433). Check with `nc`; the keepalive flags above make silent deaths much rarer — it has died mid-session three times without them.
- Use **`python -m uvicorn`**, not bare `uvicorn` — the bare binary resolved to the system
  Python 3.14 and failed with `No module named 'pydantic_settings'`.
- Port **8000 is used by `../job-tracker`** — this app runs on **8001**.
- `.env` is hidden; `ls -a` to see it. Run uvicorn **from the project root** or it won't load.
- The database (`jobagent`) and role were created via `sudo -u postgres psql` on the VM;
  `ktor_user` is **not** a superuser and cannot create roles/databases.
- Never commit `.env` or keys. DB credentials live on the server in `/etc/ktor/ktor.env`.
- `create_all` only creates MISSING TABLES — adding a **column** to an existing model needs a
  manual `ALTER TABLE` on staging (done so far: `user_activity.lang`, `postings.embedding`).
- `.env` has `INGEST_EVERY_HOURS=6` → the app spawns a background ingest thread (real network).
  Tests force it to 0 in conftest; keep it that way or the suite hangs on live fetches.
- Search now is **DB-first** (`search_db`, no network). The index is filled by the background
  ingester / `python -m app.jobs ingest`; an empty index means empty results, not a bug.

---

## 4. Data model (`app/models.py`)

`users` → `profiles` (many per user) → `matches` → `postings`;
`sources` (built-in have `user_id = NULL`, user-added have the user's id);
`applications` (tracker-style status log).

---

## 5. Conventions (follow these)

- **Clean Architecture** *(required)*: the code is organized in four layers with dependencies
  pointing inward — see `docs/architecture.md` for the full map:
  - `app/core/` — configuration.
  - `app/domain/` — **pure business logic** (entities, scoring, extraction, filters, dedup,
    taxonomy, activity rules, text utils). No FastAPI, no SQLAlchemy, no I/O — fully unit-testable.
  - `app/data/` — I/O: DB (`db`, `models`), auth crypto, mailer, repositories
    (`activity_repo`, `metrics_repo`, `ingest`) and **`sources/`** (one isolated adapter per
    job source).
  - `app/application/usecases/` — orchestration (`search.py` = Search-now pipeline,
    `digest.py` = daily digest); `run_stats.py` = metrics collector.
  - `app/presentation/` — HTTP layer: `web.py` shell, `seo.py`, `i18n.py`, `routers/`.
  - Entrypoints (composition roots): `app/main.py` (web), `app/jobs.py` (cron),
    `app/metrics.py` (CLI).
  Rule of thumb: domain must import nothing from other layers; data may import domain;
  application may import domain+data; presentation may import all. New functionality drops in
  as a self-contained module in the right layer — a change should touch a **small** file.
  *(MVI is deliberately NOT used here — it's a client-side UI pattern; it becomes relevant for
  the Phase 4 frontend, where client state exists.)*
- **Documentation in English, kept current** *(required)*: `docs/architecture.md` (layers,
  dependency rule) and `docs/features/*.md` (one file per functionality — what it does + which
  modules implement it). Update the relevant doc in the same change that alters behaviour.
- **One adapter per source (isolation)** *(required)*: every job source — platform, service,
  site, API, feed, without exception — gets its **own dedicated adapter module**
  (`app/adapters/<source>.py`) behind the common interface, with its **own tests**. Sources are
  brittle (HTML changes, API tweaks, rate limits); isolating each means a change to one never
  risks another, and adding a source is a new file, not an edit to shared code. The pipeline
  works only off the normalized `RawPosting`.
- **Automated tests, thorough** *(required)*: every module ships with detailed automated tests
  (`pytest` in `tests/`). Tests must run **without the SSH tunnel** — they use a temporary
  SQLite DB via a `get_db` dependency override, so they're fast and hermetic. New behaviour is
  not "done" until it has tests and `pytest` is green. Cover happy paths, validation failures,
  per-user isolation, and edge cases.
- **Server-rendered HTML** (keeps it indexable for SEO; no SPA for now). Reuse the shared shell.
- **Mobile-first**: every new page must work on a phone. The shared shell already has the
  responsive rules — reuse it, don't invent a second layout.
- **Cheap by default**: the core pipeline (find → dedup → validate → score → apply link)
  must not require a paid LLM. Scoring = local embeddings. Generative LLM only for
  CV/cover letters, and that is **BYOK** (user's own key) — see `LLM_COST_STRATEGY.md`.
- **Per-user isolation** on every query — a user must never see another user's data.
- **Verify before declaring done**: `python -m py_compile`, run `pytest`, and exercise the real
  route (live server or `TestClient`). Don't say "done" on unrun code.
- **Honest over impressive** — if something is a stretch or unverified, say so.

## 6. Hard rules

- **No auto-apply.** We only open the application page; a human submits.
- **No ToS-violating scraping.** Prefer ATS/board APIs → RSS → the user's own logged-in
  browser session. Aggregators (e.g. RemoteRocketship) are unreliable: paywalled apply
  links and stale/expired postings.
- **Secrets never in the repo.**

---

## 7. Next steps

**Finish Phase 1** — done so far (all tested; see `tests/`):
1. ✅ Profile edit/delete + form validation.
2. ✅ Requirement extraction moved to `app/extraction.py` (rules-based must/nice/resp).
3. ✅ Covered/missing shown as chips; `min_match` tunable from the list view.
4. ✅ Google OAuth: credentials added, flow verified live.
5. ✅ GDPR account export + delete.
6. ✅ SEO foundation: per-page title/description/canonical/OG, `robots.txt`, `sitemap.xml`,
   Organization/WebSite JSON-LD on the landing; **private pages are noindex by default**
   (`app/seo.py`, `app/routers/seo.py`). `JobPosting` schema deferred until public job pages
   exist (Phase 2/4).
7. ✅ BG/EN i18n scaffolding (`app/i18n.py`): dict catalog + `t()` + language resolution
   (URL → cookie → Accept-Language → en). Public landing is language-prefixed (`/` en, `/bg`)
   with **hreflang**; login/register + nav localized. Internal screens are English-only for
   now (keys ready in the catalog).

**Phase 1 is complete.** Next is **Phase 2 — auto-fetch** (see `ROADMAP.md` steps 8–17):
ATS API + RSS adapters, dedup, requirement extraction on fetched postings, apply-link
resolver, scheduler. This is where the real product value (skills in → matches out) lands.

**Then Phase 2 (auto-fetch)**
Adapters in priority order: ATS APIs (Greenhouse/Lever/Ashby/Workable — these also give the
canonical apply URL), then RSS (RemoteOK / WeWorkRemotely), then the logged-in browser for
LinkedIn. Add dedup **before** scoring, a scheduler, and a "seen/applied" filter.

**Also queued:** SEO foundation (titles/meta, robots, sitemap, schema.org `JobPosting`,
public landing pages), GEO (AI-search visibility), BG/EN localization + geo pages.

---

## 8. Prompting the models (required reading before writing agent prompts)

The agents that call an LLM are A0 (profile normalise), A4 (requirement extraction),
A6 (only for explanations) and A9 (CV / cover letter). Everything else is plain code.

**Our conventions:**
- **Extraction (A0/A4): cheap model, low temperature, schema-constrained JSON output.**
  Give the model the exact JSON shape and validate it (Pydantic) — never parse prose.
- **Never send a whole page** into the model. Strip boilerplate first; token cost is a
  product cost, and for BYOK it is the *user's* money.
- **Generation (A9): quality matters** — this is where a stronger model earns its price.
  Pass the structured profile + structured requirements, not raw text, and state the
  constraints explicitly (tone register, CEFR level, "do not invent experience").
- **Always give the model a way to say "unknown"** rather than forcing a guess — a fabricated
  requirement or skill is worse than a blank.
- **Keep prompts in one place** (a `prompts/` module), versioned, so they can be evaluated and
  improved rather than scattered inline.
- **Evaluate before shipping a prompt change**: keep a small fixed set of postings/profiles
  and compare outputs.

**Provider documentation** (we support several via BYOK):
- Anthropic — https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview
- OpenAI — https://platform.openai.com/docs/guides/prompt-engineering
- Google Gemini — https://ai.google.dev/gemini-api/docs/prompting-strategies
- Groq — https://console.groq.com/docs
- Ollama (local fallback) — https://github.com/ollama/ollama/blob/main/docs/api.md

When adding a provider, read its prompting guide first: structured-output support and system
prompt behaviour differ, and that is exactly where cross-provider bugs come from.

## 9. Open decisions

See `DECISIONS.md` §12 and the LLM doc §7 — mainly: which BYOK providers ship first,
free local-generation limits, and hosting (one small VPS to start).
