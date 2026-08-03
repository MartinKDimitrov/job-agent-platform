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
FOUR doors — exact title tokens, **semantic** (E5 cosine ≥ `recall_min_cosine`), a shared
canonical skill, or the **rank door** (`ranked_candidates`: the profile's N nearest postings
above a LOW floor `recall_rank_floor`=0.70) — then trimmed to `recall_max_candidates`. The rank
door exists because the absolute cosine bar was calibrated on long IT profiles; short trade
titles never reach it (welder vs "Заварчик" = 0.763 at a 0.87 bar), so entire professions
recalled nothing. Rank has no such bias — everybody gets their own best candidates, scoring
decides what survives. **Every door is geo-screened BEFORE spending candidate budget**
(`geo_narrowing`: country names + ISO codes as word-regex SQL predicate): a Bulgarian welder's
800 nearest postings are all Irish, so an unscreened ANN burned the whole budget on rows the
location filter dropped a moment later. HNSW post-filters, so narrowed queries switch to an
exact scan (`enable_indexscan=off`) — pgvector caps `ef_search` at 1000 and silently falls back
to ~40 above it. The **profile embedding is cross-lingual**: the ESCO occupation's names in ALL
languages are prepended to the embed input (`role_names_all_languages`), lifting
welder↔Заварчик from 0.758 to 0.864 — a ~380k multilingual index must match profiles written
in any of its 13 source languages. The semantic door runs **server-side
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
  honoured unless the user ticked *willing to relocate*; EU-wide passes for EU residents).
  City-level: `geo_relation` tiers a posting as **preferred** (the user's city / remote),
  **elsewhere** (hard drop for onsite), or **unsure** — unknown place, or a bare-country
  location in the user's own country when they named a city — which stays visible but ×0.8
  (below the 65% default threshold in dense feeds). Tokenizer is all-Unicode (Greek script was
  invisible to `\w`), country aliases include native spellings (España/Polska/Ελλάδα/…);
- **no-requirements rule**: zero extracted must/nice = blind scoring → never shown.

**Scoring** — one formula everywhere (`domain.scoring.blend`):
`0.35 × semantic + 0.65 × weighted coverage` (must 1.0 / nice 0.4 / resp,soft 0); semantic
= rescaled E5 cosine of the stored vectors. Covered/missing stored per Match for the UI panels.
Guardrails, each from a real bad feed:
- **sem-only scaled cap** (`semantic_only_cap`=0.75): a posting with no scoreable requirements
  rides on similarity alone — scaled, not flat, so ordering inside the capped band survives;
- **title-names-role exception** (`semantic_title_cap`=0.92): when the posting TITLE names the
  candidate's own occupation (any ESCO language, `_title_names_role`), the cap loosens — "Заварчик"
  hiring a welder shouldn't score under a keyword-rich unrelated ad;
- **education requirements** (`education_hit`): a degree requirement at/below the candidate's
  stated `qualification_level` counts covered — and OVERRIDES the LLM verifier, which reads only
  the profile text and can't see the structured level ("казах, че имам висше, а пак го пише
  като липсващо"). An education-only single requirement is no evidence (no-requirements rule);
- **single raw requirement damping** (×0.75 on coverage): one extracted skill-less requirement
  line is too thin to claim full coverage; annotated ★-weighted postings are exempt.

**Soft factors** (`soft_factors` — one product multiplied onto the base score; also the single
source for the "why this score" breakdown, so number and explanation never drift): freshness,
salary fit, language/CEFR, seniority, **role-family**, location, **qualification**.
- *role-family* (`domain.role_family`): a target-family vs posting-family conflict — HARD drop for
  disjoint disciplines, SOFT down-weight for adjacent ones. Covers the tech families **and** the
  non-tech ESCO verticals (construction, trades, transport, agriculture, education, legal, admin,
  hospitality, finance, healthcare, sales, marketing) — so a concrete-finisher profile no longer
  false-matches a DevOps role. Acts only when both sides name a concrete family. Cues are
  **generated multilingual** from ESCO (`python -m app.tools.build_role_family_i18n`: labels whose
  occupations sit ≥60% in one family; short labels only, DENY list for universal words), with
  Cyrillic-aware boundaries for short cues ("одит" matched inside "ръковОДИТел"). Healthcare is
  split into sub-professions (physio/rehab/nursing/midwifery/doctor/dental/pharmacy/medlab/care) —
  owner rule: "Рехабилитатор/Кинезотерапевт/Медицинска сестра/Акушерка са различни професии";
  the generic "healthcare" marker stays soft-adjacent to each.
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

**Quality gates (run BEFORE a release):**
- `python -m app.tools.release_check` — 100 realistic profiles (in-memory, never persisted — no
  demo data on staging) through the PRODUCTION recall+scoring path; flags broken recall, hard
  domain conflicts in the top, boilerplate shown as missing requirements (multilingual patterns),
  education-level misses, score sanity. Exit 1 gates the release; averages hide exactly these
  per-person failures. Owner makes the final call on flagged output.
- `python -m app.tools.eval_silver` — silver-oracle ranking eval at scale (role-family labels),
  answers "did ranking get better on average"; `--compare-models` A/Bs embedding models (that run
  is why we stayed on e5-small: e5-base showed no matching gain at ~4× CPU).

**Modules:** `application/usecases/search.py`, `ingest_job.py`, `verify_coverage.py`;
`domain/scoring.py`, `extraction.py`, `filters.py`, `prompts/verify_v1.py`;
`presentation/routers/profiles.py` (CRUD incl. country/relocate, feed);
`tools/release_check.py`, `tools/release_profiles.py`, `tools/eval_silver.py`,
`tools/refresh_postings.py` (requirements→education→embedding consistency re-runs).

**Tests:** `tests/test_crawl.py`, `test_ingest_job.py`, `test_scoring.py`,
`test_extraction.py`, `test_filters.py`, `test_posting_age.py`, `test_verify.py`,
`test_profiles.py`.
