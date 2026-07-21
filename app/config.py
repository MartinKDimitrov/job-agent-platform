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
