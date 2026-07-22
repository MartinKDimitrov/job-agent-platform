"""Cron entrypoints (composition root — the logic lives in app/application/usecases/):

    python -m app.jobs           # daily digest (search + email new matches)
    python -m app.jobs ingest    # refresh the posting index (DB-first search WRITE side)
"""
import sys

from .application.usecases.digest import run_daily_digest  # noqa: F401  (re-export)
from .application.usecases.ingest_job import run_ingest    # noqa: F401  (re-export)

if __name__ == "__main__":
    from .data.db import SessionLocal
    mode = sys.argv[1] if len(sys.argv) > 1 else "digest"
    with SessionLocal() as db:
        if mode == "ingest":
            print(run_ingest(db))
        else:
            print(run_daily_digest(db, jobtiger_limit=20))
