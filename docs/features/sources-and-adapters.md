# Sources & Adapters

**What it does:** fetches job postings from many sources, each through its own **isolated
adapter module** producing the normalized `RawPosting`. A change to one source can never break
another (hard rule). Live platforms:

| Adapter | Kind | Notes |
|---|---|---|
| `greenhouse.py` | ATS API | public board API (`?content=true`); `absolute_url` canonical |
| `lever.py` | ATS API | public postings API; `applyUrl` canonical |
| `ashby.py` | ATS API | public job-board API; `isRemote` annotated into location |
| `workable.py` | ATS API | POST v3 list + v2 detail (the v1 widget is dead); description / requirements / benefits are SEPARATE fields — benefits never enter the text; paced detail GETs |
| `smartrecruiters.py` | ATS API | offset-paginated list + per-posting detail; marketing/benefits sections skipped; **probe requires totalFound>0** — the API answers 200 for ANY slug (105 phantom boards once, rolled back) |
| `recruitee.py` | ATS API | one GET per company (`{slug}.recruitee.com/api/offers/`); separate description/requirements |
| `personio.py` | ATS XML | `{slug}.jobs.personio.de|com/xml`; named sections become plain-text headers |
| `teamtailor.py` | RSS | `<careers-site>/jobs.rss` — works on CUSTOM domains (careers.mypos.com) |
| `jsonld_careers.py` | generic HTML | robots-checked; schema.org JobPosting on/behind any careers page; companies activate via `python -m app.tools.probe_jsonld` |
| `dev_bg.py` | RSS | global feed (recency window) + per-profile targeted search feed; company derived from URL slug vs guid/title (repost `-1-1` suffixes handled) |
| `jobtiger.py` | sitemap+HTML | `ClaudeBot Crawl-Delay: 30` honoured; daily job only |
| `remoteok.py` / `wwr.py` | JSON / RSS | global remote boards; run on every ingest |
| `jobtech.py` | open API | Platsbanken (Sweden, Arbetsförmedlingen) — fully open JobSearch API, no key; TARGETED like dev.bg: one search per unique profile role term per cycle (full dump ≈100k postings). First adapter of the EU-boards plan (next: Arbeitsagentur DE, France Travail, EURES) |

**Company registry** (`companies` table: name, industry, website, careers_url, ats/slug,
active — 165+ real BG employers over 19 industries): one adapter serves every company on the
same platform. Tools:
- `python -m app.tools.detect_companies [--force]` — probes name-derived slugs on all ATS;
- `python -m app.tools.find_careers` — finds careers pages from websites (homepage link →
  common paths, asset links filtered) and runs detection against them — how custom-domain
  boards (myPOS→Teamtailor) are found;
- **always verify a probe hit's identity** before crawling (feed/channel names, offices) —
  greenhouse/bulgaria was capSpire, personio/kbc a Munich firm; phantom boards mislabel data.

**Shared HTTP** (`data/sources/http.py`): browser-like headers, JSON GET/POST, `url_status`,
and a **per-host 429 backoff cache** (Retry-After honoured, 15 min default) — one rate-limit
answer silences the whole host instead of extending its penalty window (Workable sent a
Retry-After of 8 hours once).

**Deliberately skipped:** jobs.bg (403s everything — we don't scrape against a site's
expressed will), LinkedIn auto-search (ToS). The /sources page lists ONLY platforms an
adapter actually crawls — no aspirational entries (owner rule; also: no demo data anywhere).

**Tests:** `tests/test_adapters_*.py`, `tests/test_companies.py`, `tests/test_sources.py`,
`tests/test_http_backoff.py`.
