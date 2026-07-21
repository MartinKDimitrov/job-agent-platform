# Search & Scoring

**What it does:** "Search now" on a profile fetches postings from the fast sources, keeps ones
whose title matches the profile's keywords (cheap pre-filter), ingests them (dedup), applies
**hard filters** (a management role is dropped for an IC profile; junior roles for senior
profiles; onsite roles in non-preferred locations for remote candidates), extracts structured
requirements from each JD, scores each surviving posting against the profile, and shows
matches ≥ the profile's threshold with covered/missing chips and a direct Apply link. The
threshold (`min_match`, default 65%) is tunable inline from the list.

**Scoring** = local E5 embeddings semantic similarity (free, CPU) blended with weighted
requirement coverage (must-have > nice-to-have; responsibilities shown but not scored),
falling back to keyword-only when the model is unavailable.

**Modules**
- `application/usecases/search.py` — the pipeline (`run_search`, `fetch_all`, `fetch_extra`,
  source lists, per-source error isolation).
- `domain/scoring.py`, `domain/extraction.py`, `domain/filters.py` — the pure logic.
- `data/ingest.py` — persistence + dedup application.
- `presentation/routers/profiles.py` — profile CRUD, search route, results view.

**Tests:** `tests/test_crawl.py`, `tests/test_scoring.py`, `tests/test_extraction.py`,
`tests/test_filters.py`, `tests/test_profiles.py`.
