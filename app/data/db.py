from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config import settings


def _engine_kwargs(url: str) -> dict:
    """Bound every DB failure mode so a dead staging SSH tunnel can't freeze a worker forever.
    Without these the background ingester hung indefinitely when the tunnel died mid-query: a
    silently-dropped (half-open) socket has no RST, so psycopg2's read blocks until the OS default
    keepalive (~2h) — the thread recorded no runs for 10h. connect_timeout caps the initial
    connect; the TCP keepalives detect a dead peer in ~30-60s; statement_timeout caps any single
    query server-side; pool_recycle drops connections a long-lived tunnel may have staled.
    Postgres/psycopg2 only — SQLite (tests) takes none of these."""
    kw = {"pool_pre_ping": True, "future": True}
    if url.startswith("postgresql"):
        kw["pool_recycle"] = 900
        kw["connect_args"] = {
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
            "options": "-c statement_timeout=120000",
        }
    return kw


engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables and seed built-in sources. Called on startup."""
    from . import models  # noqa: F401  (register models on Base)
    Base.metadata.create_all(bind=engine)
    from .seed_sources import seed_builtin_sources
    with SessionLocal() as db:
        seed_builtin_sources(db)
