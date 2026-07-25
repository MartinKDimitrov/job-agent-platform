"""Cron entrypoints (composition root — the logic lives in app/application/usecases/):

    python -m app.jobs                  # daily digest (search + email new matches)
    python -m app.jobs ingest           # one-shot refresh of the posting index (WRITE side)
    python -m app.jobs ingest_window    # sharded, paced nightly crawl (00:00–08:00); one cron
                                        # line — the process sleeps between country shards
    python -m app.jobs detect_window    # sharded, paced ATS detection over pending companies
"""
import sys

from .application.usecases.digest import run_daily_digest      # noqa: F401  (re-export)
from .application.usecases.ingest_job import run_ingest        # noqa: F401  (re-export)
from .application.usecases.ingest_window import run_ingest_window  # noqa: F401  (re-export)
from .application.usecases.detect_window import run_detect_window  # noqa: F401  (re-export)

if __name__ == "__main__":
    from .data.db import SessionLocal
    mode = sys.argv[1] if len(sys.argv) > 1 else "digest"
    if mode == "ingest_window":
        print(run_ingest_window(SessionLocal))     # long-running: paces itself across the window
    elif mode == "detect_window":
        print(run_detect_window(SessionLocal))     # long-running: paced detection shards
    elif mode == "ingest":
        with SessionLocal() as db:
            print(run_ingest(db))
    else:
        with SessionLocal() as db:
            print(run_daily_digest(db, jobtiger_limit=20))
