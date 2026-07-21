"""Cron entrypoint for the daily digest: `python -m app.jobs` (composition root — the logic
lives in app/application/usecases/digest.py)."""
from .application.usecases.digest import run_daily_digest  # noqa: F401  (re-export)

if __name__ == "__main__":
    from .data.db import SessionLocal
    with SessionLocal() as db:
        print(run_daily_digest(db, jobtiger_limit=20))
