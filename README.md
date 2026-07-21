# Job Agent Platform — Phase 1

Multi-user job-search app: register, create one or more **search profiles**, score job
openings against them with **E5 embeddings**, and open the **Apply** link directly.

This is **Phase 1** (foundation): auth, profiles, sources screen, and manual/paste-in
posting scoring. Auto-fetching, the CV generator (BYOK) and the response monitor come in
later phases — see `ARCHITECTURE.md`, `DECISIONS.md`, `LLM_COST_STRATEGY.md`.

## Stack
FastAPI · PostgreSQL · SQLAlchemy · E5 embeddings (local) · JWT cookie auth · Google OAuth (optional)

## Run locally

1. **Start Postgres** (Docker):
   ```bash
   docker compose up -d db
   ```
2. **Config:**
   ```bash
   cp .env.example .env      # edit SECRET_KEY at least
   ```
3. **Install & run:**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```
4. Open http://127.0.0.1:8000 → **Register** → **+ New profile** → open the profile →
   paste a job description under "Add a posting to score" → see the **match %** and **Apply**.

## Notes
- **Scoring:** uses the E5 model (`intfloat/multilingual-e5-small`); it downloads on first
  use (~470 MB). If `sentence-transformers` isn't installed or the model can't load, the app
  automatically falls back to **keyword-overlap scoring** so it still runs.
- **Cost:** scoring is local embeddings — no paid LLM calls (see `LLM_COST_STRATEGY.md`).
- **Google login:** optional. Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`;
  without them, email+password works and the Google button shows a friendly message.
- **Sources screen** (`/sources`): lists the built-in platforms we cover and lets a user
  **add their own** platform/link that we don't have yet.

## Data model (Phase 1)
`users → profiles (many) → matches → postings`; `sources` (built-in + per-user);
`applications` (tracker, reused from Phase 0). See `app/models.py`.

## Roadmap
- **Phase 2:** source adapters (ATS APIs + RSS + logged-in LinkedIn), dedup, scheduler → auto-populate matches.
- **Phase 3:** CV & cover-letter generator (BG+EN, CEFR-aware) via BYOK + local fallback.
- **Phase 4:** generalize to any profession (skills taxonomy), digest/notifications.
- **Phase 5:** email response monitor + scoring feedback loop.
