from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
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
