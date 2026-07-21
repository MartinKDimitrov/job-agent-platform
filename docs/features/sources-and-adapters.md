# Sources & Adapters

**What it does:** fetches job postings from multiple sources, each through its own **isolated
adapter module** producing the normalized `RawPosting`. A change to one source can never break
another (hard rule). Verified live sources:

| Adapter | Kind | Notes |
|---|---|---|
| `greenhouse.py` | ATS API | public board API; `absolute_url` is the canonical apply URL |
| `lever.py` | ATS API | public postings API; `applyUrl` canonical |
| `ashby.py` | ATS API | public job-board API; `isRemote` annotated into location |
| `dev_bg.py` | RSS | official WordPress job feed (per-category, hourly); BG IT market |
| `jobtiger.py` | sitemap+HTML | robots-permitted job pages, explicit `ClaudeBot Crawl-Delay: 30` honoured (skip-known-before-fetch, page cap, injected sleep); JSON-LD JobPosting parsing; **all professions**; daily job only |
| `remoteok.py` | JSON | global remote board; element [0] is a legal notice (skipped) |
| `wwr.py` | RSS | WeWorkRemotely; title "Company: Role" split |

**Deliberately skipped:** jobs.bg (hard-403s everything incl. robots.txt — we don't scrape
against a site's expressed will; partnership is the future path). Workable deferred (its
widget API returned no jobs for any tested slug). Future candidates: zaplata.bg, rabota.bg,
karieri.bg (robots-permitted, sitemaps available).

**Modules:** `data/sources/*.py` (one per source), `data/sources/base.py` (registry),
`data/sources/http.py` (shared HTTP with browser-like headers where needed),
`data/sources/seed_boards.py` (verified company slugs). Users can also list/add their own
sources on the Sources screen (`presentation/routers/sources.py`).

**Tests:** `tests/test_adapters_*.py`, `tests/test_sources.py`.
