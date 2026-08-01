# The Matching Pipeline — from raw posting text to "this job is good for you"

The canonical end-to-end description. Everything below runs in the background ingest cycle
(every `INGEST_EVERY_HOURS`, or `python -m app.jobs ingest` from cron) **except** the read
side, which is what a user's "Search now" triggers and answers in well under a second.

## WRITE side — once per posting, shared by all users

**1. Fetch.** Source adapters (10 platforms — see sources-and-adapters.md) pull postings:
fast sources + every active company board in the registry + profile-targeted dev.bg queries
for active users. Each adapter is error-isolated; per-host 429 backoff protects rate limits.

**2. Deduplicate & persist** (`data/ingest.py`). Two layers: content-hash (same source seen
again → touch `last_seen_at`, backfill `posted_at`) and cross-source (same normalized
employer + near-identical title → one Posting; an ATS sighting upgrades `apply_url` to the
canonical one). Long fields are clamped to column limits.

**3. Extract requirements** (`domain/extraction.py`, rules, no LLM). The JD text becomes
`[{text, kind}]` with kind ∈ **must / nice / resp / soft**:
- typography normalized (curly quotes, ellipsis headers — real-world traps from Yettel/Monzo);
- section headers steer buckets (EN+BG dictionaries; unrecognized `label:` lines skipped);
- line-level defence: salaries, benefits/perks, company marketing (unless a strong
  qualification signal), legal footers are dropped wherever they appear;
- personality lines (team player, mindset…) become `soft` — shown nowhere, weighted 0.

**4. Embed** (`domain/scoring.embed`). One multilingual E5 vector per posting, stored on the
row (`postings.embedding`). Profiles cache their vector the same way.

**5. Annotate requirements with canonical skills** (annotate-v1). One LLM call per posting
(PLATFORM key only — user keys never touch shared data; background only): each must/nice
requirement gets `skills: [...]` (canonical, lowercase; each listed skill ALONE satisfies
the requirement) and `weight: 1-5` (importance in THIS posting — Kotlin ★★★★★ vs XML ★).
Posting-level `annotation_version` + `annotation_fp` (hash of the requirement texts):
unchanged postings are never re-annotated, and bumping the version lazily re-annotates
only affected postings when the model/logic changes. This is what makes per-user coverage
deterministic (skills ∩ annotation — instant, shared across users with similar
qualifications) and demotes the per-user LLM verification to a fallback for postings the
annotator hasn't reached.

**6. Hygiene** *(age handling being reworked — see evolution plan)*: PROVEN-dead postings
retire forever (404/410 URL probe for window sources; registry-board postings unseen 48h);
old-but-live postings will NOT be deleted — age moves into the score as a freshness decay
(×1.0 fresh → ×0.85 @30d → ×0.70 @60d), with only an absolute 90-day cap (config) for
window-source zombies. Re-seen postings resurrect/rejuvenate.

## READ side — per user, no network, sub-second

**7. Candidate selection** (`search_db`). Live postings whose TITLE shares an exact token
with the profile keywords (generic tokens like git/api/sdk excluded).

**8. Hard filters** (`domain/filters.py`) — drop before any scoring, reason recorded:
- **seniority**: management roles for IC profiles, junior roles for seniors;
- **location**: onsite/hybrid outside the preferred locations for remote-seeking users;
- **geo**: country-restricted postings ("Remote (UK)", "eligible to work in the US") unless
  it's the user's country or they ticked *willing to relocate*; EU-wide passes for EU
  residents;
- **no-requirements rule**: zero extracted must/nice = scoring would be blind → never shown;
- matches created before a newer filter existed are deleted retroactively on each search.

**9. Score** (`domain/scoring.py`). One formula everywhere (`blend`):
`score = 0.35 × semantic + 0.65 × coverage`, where semantic = rescaled E5 cosine of the two
stored vectors and coverage = weighted requirement hits (must 1.0, nice 0.4, resp/soft 0).
Without requirement evidence similarity alone is capped at 60% (and such postings are
filtered out anyway, see 8). Covered/missing lists are stored on the Match for the UI.

**10. Verify coverage** (`verify_coverage.py`, verify-v1). For the top matches above the
user's threshold (budget `VERIFY_TOP_N`/search, cached forever per match): an LLM re-labels
hits the token overlap got wrong ('api' is not GraphQL, 'A2' is not fluent English), the
score is recomputed through the SAME `blend`, and the card gets the "✦ AI-checked" chip.
Provider chain: user BYOK → platform free lane → silent no-op; failures leave the match
untouched. Step 5 will make most of this deterministic (skills ∩ annotation) — the LLM
pass then remains only as fallback.

**11. Show / notify.** The feed lists matches ≥ `min_match` (ring, covered / not-in-profile /
considered-an-advantage panels, source badge, Apply + CV/Letter buttons). The daily digest
emails only never-notified matches for active users, in the user's language. Public SEO
pages show titles/counts only — descriptions and apply links stay behind registration.

## Invalidation summary

| Change | What recomputes |
|---|---|
| profile edited | its vector + all its matches (cleared, next search rebuilds + re-verifies) |
| posting re-extracted (extractor release) | its requirements → annotation fp mismatch → re-annotated; matches rescore on next search |
| annotate-vN bumped (new model/logic) | lazy re-annotation of every posting on its next ingest touch |
| nothing changed | nothing — vectors, requirements, annotations and verifications are all cached |

## Consolidated improvement plan (owner discussions, 2026-07-23/24)

**Phase 0 ✅ — the bottleneck first**: a hand-labeled EVAL SET (30-50 profile→posting pairs,
NDCG/P@K harness, `app.tools.eval_matching`). Five open decisions hang on it: E5 mode, recall
threshold, near-dup threshold, blend weights, ★5 cap. Also: the profile's embed input becomes
role+skills+experience (mirror of the posting's title+requirements; languages/CEFR are filter data).
- **Silver-label eval at scale** (`app.tools.eval_silver`): the hand set is too small (3 profiles)
  to separate close calls. This harness grades EVERY long-description live posting against a
  12-profile panel via `role_family` (overlap=2 / soft=1 / else=0) — coarse but scales to ~38k
  postings, reporting NDCG@10 / P@5 / MAP / Recall@20. Use for RELATIVE A/B (`--variants`,
  `--compare-models`) under identical labels, not as an absolute bar. It's what measured
  e5-base = no gain over e5-small at ~4x cost; production is `asym_clean` on e5-small.

**Phase 1 ✅ (partial: mode A/B, truncation, coverage noise; weight-drift pending annotation completion)** (measure, don't guess): E5 symmetric vs passage:/query: A/B on
the eval set; token-length/truncation stats; annotation weight drift (re-annotate 10-20
postings twice); must-gate behaviour today; posted_at trustworthiness per adapter.

**Phase 2 ✅ — vector migration** (shipped: e5-asym-clean-v2, SEMANTIC_WEIGHT=0.5) (one re-embed): embed CLEAN text (title + extracted
requirements — raw 7k-char descriptions truncate at E5's 512 tokens exactly where the
requirements live); mode per eval; store embedding_version (+model/mode) on the row.

**Phase 3 ✅ — canonical skills dictionary** (skills-v1, ~90 canonical entries), applied on BOTH sides (annotation output at
write AND requirement_hit/profile at read — so dictionary updates act instantly, no
re-annotation machinery); doubles as the synonym layer for token-fallback; BG/EN aliases;
unknown skills from both sides are logged and reviewed — that's what keeps it alive.

**Phase 4 ✅ — scoring hardening** (shipped; near-dup gates tightened after a live false-merge lesson: cross-host only): all weights/thresholds in config; must-gate v1 (a ★5 must
with ZERO overlap across its annotated alternatives → hard cap; class-equivalence only as
a validated soft near-miss later); ★5 cap per posting (config, tuned on eval); freshness
decay (posted_at, fallback first_seen, per-adapter date-trust flag); dealbreaker/negation
patterns folded into the existing hard filters; near-dup merge GATED (cosine >0.94 AND
same normalized company AND title similarity — reworded reposts only, never
Finance-vs-Healthcare false merges); LOW-extraction escalation (long description but <3
requirements → retry big model / verify-fallback).

**Phase 5 ✅ — recall** (hybrid 3-door + in-process vector cache; pgvector live on staging for the deploy-scale SQL path): hybrid candidates — title token OR vector proximity (threshold from
eval + candidate-set size) OR at least one shared canonical skill (same generic-token
stop-list as titles, or one popular skill floods the set); targeted dev.bg queries grouped
by UNIQUE ROLE across users (one query per role per cycle), not per profile. Vector-door
threshold calibrated on the LIVE cosine distribution (median ~0.81, p99 ~0.87, true role
matches 0.88+): RECALL_MIN_COSINE=0.87 — the initial 0.80 sat below the E5 floor and
admitted everything.

**Phase 6 ✅ — observability & explainability**: component breakdown on the match card
(semantic / requirements coverage / freshness — recomputed at render via the same domain
functions as scoring, so it cannot drift) + muted "skills of yours this posting doesn't
ask for" chips in the gaps panel (canonical-dictionary diff); feedback capture — 'shown'
stamped cheaply as Match.first_shown_at on first render, deliberate acts in the
feedback_events table: Apply goes through an internal /go redirect that logs `applied`
before forwarding (substrate for the applications dashboard), a Hide button sets
Match.hidden + logs `hidden` (future learning loop); unknown-skill counter from
annotation lands in ingest stats/CrawlRun — a spike there means the market outgrew the
skills dictionary.

**Phase 7 ✅ — salary**: `domain/salary.py` parses the RAW posting text at ingest (before
extraction drops money lines): ranges, 9 currencies incl. symbol-before ("€55,000–€70,000",
"$120k"), monthly/annual keywords in 13 languages with size-based inference as fallback;
deliberately conservative — a number counts only with a currency signal adjacent, plus
plausibility floors (years and "5+ years" never parse). Stored on Posting
(salary_min/max/currency/period/raw), shown on the card as written. Score effect is SOFT
and fires only when BOTH sides state a number in comparable currencies (BGN↔EUR pegged
conversion only, annual normalized to monthly): posting max >20% below the expectation →
×SALARY_LOW_FACTOR (0.85); posting min already meets it → ×SALARY_FIT_BOOST (1.05, capped
at 100); everything else — including currencies we can't compare — strictly neutral.
Applied identically in search_db and the LLM verification recompute. Live: 582/1494
postings (39%) state a parseable salary.

**Deliberately skipped** (await data or scale): feedback-driven reranking / learned
weights, ColBERT/BM25 hybrid, company reputation prior, CV/LinkedIn auto-profile,
A/B framework, ANN/pgvector (at deploy scale), personalized thresholds (min_match exists).
