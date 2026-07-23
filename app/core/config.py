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
