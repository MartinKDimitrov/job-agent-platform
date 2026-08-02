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

**Hybrid recall** (`application/vector_cache.py`): a posting is a candidate through ANY of
three doors — exact title tokens, **semantic** (E5 cosine ≥ `recall_min_cosine`), or a shared
canonical skill — then trimmed to `recall_max_candidates`. The semantic door runs **server-side
on Postgres via pgvector's HNSW index** (`embedding <=> q`, `ef_search` raised to the cap), so a
search never pulls the ~387k×384 vector matrix over the tunnel — that measured ~90s + ~600MB RAM,
now ~0.16s indexed (≈98% ANN recall at the boundary, immaterial for a trimmed candidate door).
SQLite (tests) has no pgvector, so it falls back to an in-process numpy matrix. The skill door's
per-posting canonical-skill sets stay cached in RAM (rebuilt after each ingest, warmed off the
request path at startup); the E5 model is likewise warmed at startup so the first search pays
neither the ~80s model cold-load nor the vector reload.

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

**Soft factors** (`soft_factors` — one product multiplied onto the base score; also the single
source for the "why this score" breakdown, so number and explanation never drift): freshness,
salary fit, language/CEFR, seniority, **role-family**, location, **qualification**.
- *role-family* (`domain.role_family`): a target-family vs posting-family conflict — HARD drop for
  disjoint disciplines, SOFT down-weight for adjacent ones. Covers the tech families **and** the
  non-tech ESCO verticals (construction, trades, transport, agriculture, education, legal, admin,
  hospitality, finance, healthcare, sales, marketing) — so a concrete-finisher profile no longer
  false-matches a DevOps role. Acts only when both sides name a concrete family.
- *qualification* (`qualification_factor`): down-weights a posting demanding a much higher formal
  education (NKPD level gap ≥ 2) than the candidate has. The profile's level is what the CANDIDATE
  states in onboarding / profile edit, falling back to the level their occupation implies via the
  NKPD overlay ([onboarding](onboarding.md)). The posting's is `Posting.education_level`, collected
  once at enrichment (`extract_qualification_level`, multilingual) instead of re-scanning every
  candidate's description on every search. Conservative: unknown either side → no effect, and when
  several levels appear the ENTRY bar wins ("Bachelor's or Master's" = 6), since over-reading the
  bar penalises candidates the posting would accept. Cues match on word boundaries and "master"
  must be degree-shaped — a 400k backfill showed bare substrings reading German "abSChluss" as a
  BSc and "Master Technician"/"master data"/k8s "masters" as a Master's degree.

**LLM coverage verification** (verify-v1): top matches above the threshold get a budgeted
(`VERIFY_TOP_N`), cached-forever, best-effort LLM re-labeling of hits ('api' ≠ GraphQL,
'A2' ≠ fluent English); scores recompute through the SAME blend; "✦ AI-checked" chip.
Provider chain: user BYOK → platform free lane → silent no-op. From the user's search it runs
**off the request path** (`verify_top_matches_async`, daemon thread + own session): the feed
returns immediately and the verified split lands on the next page load — a profile with many
fresh matches was otherwise paying up to `VERIFY_TOP_N` rate-limited LLM calls inline (~18s).
Batch callers (digest) still verify synchronously.

**UI (one-page app, EN/BG):** profile tabs + threshold tuner + Search now; match cards with
score ring, covered / not-in-your-profile / considered-an-advantage panels, source badge,
Apply + CV/Letter buttons.

**Modules:** `application/usecases/search.py`, `ingest_job.py`, `verify_coverage.py`;
`domain/scoring.py`, `extraction.py`, `filters.py`, `prompts/verify_v1.py`;
`presentation/routers/profiles.py` (CRUD incl. country/relocate, feed).

**Tests:** `tests/test_crawl.py`, `test_ingest_job.py`, `test_scoring.py`,
`test_extraction.py`, `test_filters.py`, `test_posting_age.py`, `test_verify.py`,
`test_profiles.py`.
