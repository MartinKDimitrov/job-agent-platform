from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://jobagent:jobagent@localhost:5432/jobagent"
    secret_key: str = "change-me"
    access_token_minutes: int = 10080  # 7 days

    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_base: str = "http://localhost:8000"

    e5_model: str = "intfloat/multilingual-e5-small"
    # Blend weight of the semantic component (coverage gets 1 - this). Raised 0.35 -> 0.5
    # per the eval-v1 sweep (peak ~0.8 on the small set; cautious step, recalibrate as the
    # eval set grows).
    semantic_weight: float = 0.5

    # DB-first search: the in-app background ingester refreshes the posting index every
    # N hours (0 = disabled — tests and environments where cron runs `python -m app.jobs ingest`).
    ingest_every_hours: int = 0
    # Windowed ingest (`python -m app.jobs ingest_window`): the daily crawl runs sharded by
    # country and paced across [start_hour, end_hour) local, so it never runs as one long
    # single-point-of-failure burst and spreads HTTP load. Big countries are sub-sharded into
    # batches of `ingest_shard_batch` boards. Default window: 00:00–08:00.
    ingest_window_start_hour: int = 0
    ingest_window_end_hour: int = 8
    ingest_shard_batch: int = 200
    # Detection (`python -m app.jobs detect_window`) reuses the same nightly window but is
    # heavier per company (careers discovery + ATS probing, ~20–40 requests each), so its
    # shards are smaller. Schedule it on its own nights / offset from ingest.
    detect_shard_batch: int = 100

    # Adzuna — multi-country job aggregator API (free trial keys from developer.adzuna.com).
    # Silent no-op until both are set. Covers DE/FR/IT/GB/ES/NL/PL in one source.
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    # Jooble — pan-European aggregator API (free key from jooble.org/api/about). The one
    # aggregator that natively covers BG + the Baltics. Keyword-driven; silent no-op unless set.
    # Free tier is capped at 500 requests TOTAL, and we spend one per role term per run, so cap
    # the terms queried per run to keep the quota alive (raise once the limit is lifted).
    jooble_api_key: str = ""
    jooble_max_terms: int = 25
    # Careerjet — global aggregator (90+ countries incl. BG), v4 API with Basic auth (free
    # publisher key from careerjet.com/partners/api). Silent no-op until the key is set.
    # user_ip is a required API param; default is a server-side geo placeholder, overridable.
    careerjet_api_key: str = ""
    careerjet_user_ip: str = ""
    # Absolute zombie cap: postings older than this retire outright (window sources where a
    # takedown can't be proven). Below it, age enters the SCORE as freshness decay instead
    # (owner decision: no more blanket deletion at 30 days).
    posting_max_age_days: int = 90
    # Freshness decay knees: full score through fresh_days, then linear to f30@30d, f60@60d.
    freshness_fresh_days: float = 7.0
    freshness_at_30d: float = 0.85
    freshness_at_60d: float = 0.70
    # Must-gate: a ★5 must with zero coverage across its annotated alternatives caps the
    # score here (0 disables the gate).
    must_gate_cap: float = 0.40
    # Max ★5 requirements per posting — small models inflate importance, and an inflated
    # ★5 arms the must-gate (post-rule on annotation; tune on the eval set).
    five_star_max: int = 3
    # Near-dup merge: cosine threshold (same-company + CROSS-host + similar-title gates —
    # same-host pairs never merge; see merge_near_duplicates).
    near_dup_cosine: float = 0.96
    # Hybrid recall (Phase 5): a posting is a candidate when its TITLE shares a token, OR
    # its vector cosine >= this, OR it shares a non-generic canonical skill. Guard rail:
    # cap on the candidate set so a loose threshold can't flood scoring.
    # Calibrated on the live distribution: profile-vs-index cosine has median ~0.81 and
    # p99 ~0.87, while TRUE role matches sit at 0.88+ — 0.87 admits the real semantic
    # neighbours and keeps 'Customer Success' (0.835) out.
    recall_min_cosine: float = 0.87
    recall_max_candidates: int = 400
    # Takedown URL probes per ingest cycle for window sources (0 = off; tests force 0 —
    # the probe makes REAL network requests to dev.bg etc.).
    takedown_probe_budget: int = 30
    # Salary soft signal (Phase 7) — fires only when BOTH sides state a number in comparable
    # currencies: multiplier when the posting pays clearly below the expectation / meets it.
    salary_low_factor: float = 0.85
    salary_fit_boost: float = 1.05
    # Language soft signal: a posting written in a non-English language the user doesn't read is
    # a real barrier (can't parse the requirements) -> down-weight. Soft multiplier, never a hard
    # filter; only fires when Profile.languages is set. English is treated as broadly readable.
    # `unreadable`: posting the user can't read / an explicit unmet language requirement (strong).
    # `foreign_country`: posting is readable (English) but the country's everyday language is one
    # the user doesn't speak (mild — many international firms work in English).
    language_unreadable_factor: float = 0.5
    language_foreign_country_factor: float = 0.9
    # Seniority soft signal (level mismatch the hard filter lets through): under-qualified = a
    # senior role for a junior candidate; over-qualified = a junior role for a senior candidate.
    seniority_underqualified_factor: float = 0.6
    seniority_overqualified_factor: float = 0.75
    # Role-family soft signal (adjacent-but-different discipline the hard filter lets through):
    # Data Scientist vs Data Engineer, Backend vs DevOps — related enough to show, different
    # enough to rank below a same-family match. Non-adjacent mismatches (QA↔Backend) are dropped.
    role_family_adjacent_factor: float = 0.8
    # Commute soft signal: a candidate who prefers remote but is willing to relocate now SEES
    # on-site / hybrid roles (the hard location filter no longer hides them) — this keeps genuine
    # remote roles ranked above the ones that would require a move.
    onsite_commute_factor: float = 0.92

    # Shared "free" document generation for users WITHOUT their own key: the platform's LLM
    # (e.g. groq free tier or a local ollama at deploy), capped per user per day. Users with
    # a BYOK key are unlimited and use their own provider. Empty provider = no free lane —
    # clicking CV/Letter then routes the user to Account to add a key.
    server_llm_provider: str = ""
    server_llm_api_key: str = ""
    server_llm_model: str = ""
    free_docs_per_day: int = 3
    # LLM coverage verification: how many top matches to double-check per search (0 = off).
    # Verified matches are never re-checked, so the cost is one-time per match.
    verify_top_n: int = 8
    # Requirement annotation (annotate-v1): LLM calls per ingest cycle on the PLATFORM key
    # (0 = off). One call per posting, ever — version+fingerprint make re-annotation lazy.
    annotate_budget: int = 60
    # Annotation is a simple structured task — a small fast model with high rate limits
    # beats the big default (groq: llama-3.1-8b-instant). Empty = the server default model.
    annotate_model: str = ""

    # France Travail (Pôle Emploi) Offres d'emploi API — free OAuth2 client credentials
    # from francetravail.io. Empty = the adapter is a silent no-op.
    francetravail_client_id: str = ""
    francetravail_client_secret: str = ""

    # Public base URL, used for absolute canonical/OG URLs, robots.txt and sitemap.xml.
    # Set to the real domain in production (e.g. https://jobagent.example).
    site_url: str = "http://localhost:8001"

    # Email (daily digest). If smtp_host is empty we run in dev mode: emails are logged, not sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "Job Agent <noreply@localhost>"


settings = Settings()
