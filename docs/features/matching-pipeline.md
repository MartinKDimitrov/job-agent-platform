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

**6. Hygiene.** `retire_stale_postings` (>30 days by source date → `is_live=False`, every
surface hides them), `retire_unseen_board_postings` (registry-board postings unseen 48h =
taken down), `probe_taken_down_urls` (budgeted 404-probe for window sources like dev.bg).
Re-seen postings resurrect unless past the age rule.

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

## Agreed evolution (owner discussion, 2026-07-23 — in priority order)

1. ✅ (this doc) annotation with version/fingerprint + per-requirement weights
2. hybrid candidate recall: title-token match OR stored-vector similarity above a threshold
   (the lexical gate alone cuts recall — "Backend" must see "Software Developer")
3. structured years-of-experience: extract `min_years` per posting + profile years; SOFT
   penalty, not a hard reject (JD year demands are often aspirational)
4. second embedding for the TITLE (role identity: QA vs Android share a stack) — also feeds
   the semantic recall of (2)
5. skills ontology: v1 synonyms/aliases (k8s=kubernetes…), v2 hierarchy via ESCO (Phase 4)
6. coverage floor (reject below N% must-coverage); dynamic blend weights deliberately
   deferred to the Phase-5 learning loop (tuning without outcome data is guesswork)
