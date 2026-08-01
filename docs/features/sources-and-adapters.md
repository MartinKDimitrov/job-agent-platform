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
| `jobtech.py` | open API | Platsbanken (Sweden, Arbetsförmedlingen) — fully open JobSearch API, no key; TARGETED like dev.bg: one search per unique profile role term per cycle (full dump ≈100k postings). First adapter of the EU-boards plan |
| `arbeitsagentur.py` | public API | Bundesagentur für Arbeit (Germany) Jobsuche API — public client key `jobboerse-jobsuche` (what the official app sends, not a secret); search (v4/jobs) + PACED per-posting details (v4/jobdetails, the v2 of older writeups is 403 now); `externeUrl` wins as apply link; description-less postings skipped (can't score). Second EU-boards adapter |
| `francetravail.py` | OAuth API | France Travail (ex Pôle Emploi) Offres d'emploi v2 — free but OAuth client credentials from francetravail.io required (FRANCETRAVAIL_CLIENT_ID/SECRET in .env; silent no-op without). In-process token cache (~25 min expiry); `origineOffre.urlOrigine` wins as apply link. Third EU-boards adapter |
| `workday.py` | enterprise ATS | The board most DAX/CAC/FTSE/IBEX giants actually run (a big firm's "careers page" is usually a Workday/SuccessFactors board, not scrapeable HTML — JSON-LD-on-landing yields ~1-4%, dead end for scale). Public CXS JSON API, no key: list POST `…/wday/cxs/{tenant}/{site}/jobs` + PACED detail GETs (full HTML description). Board id = the whole CXS base URL (3 parts: tenant, datacenter wdN, site); detection scans the careers page for the myworkdayjobs host, then verifies the tenant matches the company name (a page can link a subsidiary's board). Live: 11 DAX/CAC/FTSE/SMI giants |
| `successfactors.py` | enterprise ATS | SAP's own board + many giants not on Workday. Career Site Builder has no JSON/JSON-LD (verified jobs.sap.com) — server HTML: list `…/tile-search-results/?q=` (job-tile `data-url`s) + PACED detail scrape (`itemprop=title` + `<span class=jobdescription>`, generous window, footer trimmed). Board id = the CSB host; detection fingerprints the careers page (`job-tile`/`tile-search-results`). Per-tenant CSB theming varies, so extraction is tolerant |

**Company registry** (`companies` table: name, industry, website, careers_url, ats/slug,
active — 165+ real BG employers over 19 industries): one adapter serves every company on the
same platform. Tools:
- `python -m app.tools.detect_companies [--force]` — probes name-derived slugs on all ATS;
- `python -m app.tools.find_careers` — finds careers pages from websites (homepage link →
  common paths, asset links filtered) and runs detection against them — how custom-domain
  boards (myPOS→Teamtailor) are found;
- **always verify a probe hit's identity** before crawling (feed/channel names, offices) —
  greenhouse/bulgaria was capSpire, personio/kbc a Munich firm; phantom boards mislabel data.

**Aggregator firehose + bulk drains** (`data/sources/{adzuna,careerjet,jooble,eures}.py`,
`application/usecases/{adzuna_bulk,aggregator_drain}.py`): the post-pivot volume comes from EU
job-board APIs drained country×category (Adzuna) or country-locale feed (Careerjet/Jooble), with a
durable resumable cursor (`AdzunaPull` / `AggregatorDrain`) committed per page so a killed run
resumes exactly. Jobs modes: `adzuna_fast`, `careerjet_fast`, `jooble_fast` (concurrent), and the
sequential `adzuna_drain` / `careerjet_drain` / `jooble_drain`. Profiled 2026-07-29:
- **Concurrent fetch waves** — sequential paging is latency-bound (Adzuna ~1.5s/page → ~0.5 req/s);
  a wave fetches N pages in parallel then persists through ONE db writer (tunnel sees one
  connection). `ADZUNA_CONCURRENCY` / `AGG_CONCURRENCY`.
- **Rate ceilings differ per source.** Adzuna: `503` is soft per-request load-shedding (ignore),
  the hard limit is a **rolling `429` quota** — a short K=4 burst is fine but sustained K≥4 trips it,
  so the drain paces (K=2 + `ADZUNA_WAVE_PACE`≈2s ≈ 0.5 req/s). Careerjet has no visible limit up to
  K=8. A single gentle request succeeds throughout a 429 storm → it's a rate cap, not a lockout.
- **Depth cap** (`ADZUNA_MAX_PAGE`=100) + zero-yield retire — Adzuna serves "full" pages
  arbitrarily deep but recycles dupes past ~page 100 (~1.4% yield), so slices retire at the cap
  instead of paging to depth 1000+ for nothing.

Boards render per source (`adzuna_board`, `aggregator_board <src>`, `eures_board`) and publish as
Claude Artifacts. Owner rule: no demo data — only real pulls.

**Operational mode (2026-08).** The bulk backlog is fully drained (Adzuna 300/300, Careerjet 8/8,
EURES 17/17; ~425k postings). The always-on drain agents were stopped — a drained slice adds
nothing — and freshness now comes from a **daily recency pass** (`adzuna_recent`: date-sorted, stops
at the first already-seen posting). Two launchd agents remain: the SSH tunnel and the recency job.
Re-drain by hand (`adzuna_fast` etc.) only when new sources/quota open up.

**Shared HTTP** (`data/sources/http.py`): browser-like headers, JSON GET/POST, `url_status`,
and a **per-host 429 backoff cache** (Retry-After honoured, 15 min default, but per-host overrides
where wrong — `api.adzuna.com`→60s, since its 429 is a transient rolling-rate throttle a 15-min
stall would turn into a dead drain) — one rate-limit answer silences the whole host instead of
extending its penalty window (Workable sent a Retry-After of 8 hours once).

**Deliberately skipped:** jobs.bg (403s everything — we don't scrape against a site's
expressed will), LinkedIn auto-search (ToS). The /sources page lists ONLY platforms an
adapter actually crawls — no aspirational entries (owner rule; also: no demo data anywhere).

**Tests:** `tests/test_adapters_*.py`, `tests/test_companies.py`, `tests/test_sources.py`,
`tests/test_http_backoff.py`.
