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

    # DB-first search: the in-app background ingester refreshes the posting index every
    # N hours (0 = disabled — tests and environments where cron runs `python -m app.jobs ingest`).
    ingest_every_hours: int = 0
    # Postings older than this (source date when known, else first_seen) retire from every
    # surface — feed, public pages, digest (owner rule: nothing older than a month).
    posting_max_age_days: int = 30
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
