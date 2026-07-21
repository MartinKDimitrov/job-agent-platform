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

## 2. Current state (Phase 1 — foundation, built and running)

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

Not built yet: automatic fetching from sources (Phase 2), CV/cover-letter generator
(Phase 3), multi-profession taxonomy + digest (Phase 4), email response monitor (Phase 5),
SEO/GEO layer.

---

## 3. How to run (and the traps we already hit)

The database is the **MystyBag staging Postgres**, reachable only on that VM's localhost,
so a **SSH tunnel is required**.

```bash
# 1. Tunnel (background). Local port 5433 — 5432 is taken by a local Postgres.
ssh -i /Users/mdimitrov/Desktop/key/hetznerKey -f -N -L 5433:localhost:5432 root@88.99.175.26
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
- If the tunnel dies you get `server closed the connection unexpectedly`. Check with `nc`.
- Use **`python -m uvicorn`**, not bare `uvicorn` — the bare binary resolved to the system
  Python 3.14 and failed with `No module named 'pydantic_settings'`.
- Port **8000 is used by `../job-tracker`** — this app runs on **8001**.
- `.env` is hidden; `ls -a` to see it. Run uvicorn **from the project root** or it won't load.
- The database (`jobagent`) and role were created via `sudo -u postgres psql` on the VM;
  `ktor_user` is **not** a superuser and cannot create roles/databases.
- Never commit `.env` or keys. DB credentials live on the server in `/etc/ktor/ktor.env`.

---

## 4. Data model (`app/models.py`)

`users` → `profiles` (many per user) → `matches` → `postings`;
`sources` (built-in have `user_id = NULL`, user-added have the user's id);
`applications` (tracker-style status log).

---

## 5. Conventions (follow these)

- **Modular by default** *(required)*: split code into small, single-concern modules/routers.
  When a file grows or mixes concerns, break it up. The point is practical: a change should
  touch a **small** file, so the working context (and token cost) per edit stays low, and new
  functionality drops in as a **self-contained module** rather than swelling an existing one.
  Layout: shared shell/helpers in `app/web.py`; feature routes in `app/routers/<feature>.py`;
  `app/main.py` stays thin (app creation + `include_router`). Domain logic (scoring, extraction)
  lives in its own module, not in a route handler.
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
Remaining Phase 1 (see `ROADMAP.md`): **BG/EN i18n scaffolding**.

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
