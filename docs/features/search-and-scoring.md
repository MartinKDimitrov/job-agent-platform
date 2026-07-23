# Search & Scoring (DB-first)

**Model:** the index is WRITTEN in the background (ingest every `INGEST_EVERY_HOURS` via the
in-app daemon thread, or cron `python -m app.jobs ingest`); "Search now" only READS it — no
network on the user's path (test-guaranteed), sub-second over 1000+ postings. The canonical
end-to-end walkthrough lives in **matching-pipeline.md**.

**Ingest-time enrichment (once per posting, shared by all users):** requirement extraction
(must/nice/resp/soft), one stored E5 vector, posted_at/last_seen_at bookkeeping, hygiene:
- age rule: older than `POSTING_MAX_AGE_DAYS` (30) → retired from every surface;
- takedown: registry-board postings unseen for 48h retire; window sources (dev.bg…) get a
  budgeted 404 URL probe instead; re-seen postings resurrect unless past the age rule.

**Read side per profile** (`search_db`): exact-token title prefilter (generic tokens
excluded) → hard filters, with retroactive deletion of matches that a NEWER filter rejects:
- seniority (management vs IC, junior vs senior);
- location (onsite/hybrid outside preferred locations);
- **geo** (country restrictions incl. description phrases like "eligible to work in the US",
  honoured unless the user ticked *willing to relocate*; EU-wide passes for EU residents);
- **no-requirements rule**: zero extracted must/nice = blind scoring → never shown.

**Scoring** — one formula everywhere (`domain.scoring.blend`):
`0.35 × semantic + 0.65 × weighted coverage` (must 1.0 / nice 0.4 / resp,soft 0); semantic
= rescaled E5 cosine of the stored vectors; sem-only capped at 60%. Covered/missing stored
per Match for the UI panels.

**LLM coverage verification** (verify-v1): top matches above the threshold get a budgeted
(`VERIFY_TOP_N`), cached-forever, best-effort LLM re-labeling of hits ('api' ≠ GraphQL,
'A2' ≠ fluent English); scores recompute through the SAME blend; "✦ AI-checked" chip.
Provider chain: user BYOK → platform free lane → silent no-op.

**UI (one-page app, EN/BG):** profile tabs + threshold tuner + Search now; match cards with
score ring, covered / not-in-your-profile / considered-an-advantage panels, source badge,
Apply + CV/Letter buttons.

**Modules:** `application/usecases/search.py`, `ingest_job.py`, `verify_coverage.py`;
`domain/scoring.py`, `extraction.py`, `filters.py`, `prompts/verify_v1.py`;
`presentation/routers/profiles.py` (CRUD incl. country/relocate, feed).

**Tests:** `tests/test_crawl.py`, `test_ingest_job.py`, `test_scoring.py`,
`test_extraction.py`, `test_filters.py`, `test_posting_age.py`, `test_verify.py`,
`test_profiles.py`.
