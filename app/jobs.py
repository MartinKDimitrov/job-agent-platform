"""Cron entrypoints (composition root — the logic lives in app/application/usecases/):

    python -m app.jobs                  # daily digest (search + email new matches)
    python -m app.jobs ingest           # one-shot refresh of the posting index (WRITE side)
    python -m app.jobs ingest_window    # sharded, paced nightly crawl (00:00–08:00); one cron
                                        # line — the process sleeps between country shards
    python -m app.jobs detect_window    # sharded, paced ATS detection over pending companies
    python -m app.jobs adzuna_bulk [call_budget]  # drain ALL Adzuna professions, resumable
    python -m app.jobs adzuna_recent [call_budget]  # nightly: catch only NEW postings (date-sort)
    python -m app.jobs aggregator_fallback  # collect via Careerjet+Jooble when Adzuna is limited
    python -m app.jobs adzuna_status    # print bulk-pull progress (per country / slice)
"""
import sys

from .application.usecases.digest import run_daily_digest      # noqa: F401  (re-export)
from .application.usecases.ingest_job import run_ingest        # noqa: F401  (re-export)
from .application.usecases.ingest_window import run_ingest_window  # noqa: F401  (re-export)
from .application.usecases.detect_window import run_detect_window  # noqa: F401  (re-export)
from .application.usecases import adzuna_bulk                  # noqa: F401  (re-export)
from .application.usecases import aggregator_fallback          # noqa: F401  (re-export)

if __name__ == "__main__":
    from .data.db import SessionLocal
    mode = sys.argv[1] if len(sys.argv) > 1 else "digest"
    if mode == "ingest_window":
        print(run_ingest_window(SessionLocal))     # long-running: paces itself across the window
    elif mode == "detect_window":
        print(run_detect_window(SessionLocal))     # long-running: paced detection shards
    elif mode == "adzuna_bulk":
        budget = int(sys.argv[2]) if len(sys.argv) > 2 else adzuna_bulk.DEFAULT_CALL_BUDGET
        print(adzuna_bulk.run_bulk(SessionLocal, call_budget=budget))
    elif mode == "adzuna_drain":
        # keep pulling batches until every slice drains or the quota throttles us
        cap = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
        board = sys.argv[3] if len(sys.argv) > 3 else None
        print(adzuna_bulk.run_drain(SessionLocal, max_calls=cap, board_path=board))
    elif mode == "adzuna_recent":
        # cheap nightly maintenance: catch only NEW postings (date-sorted, stop at first-seen)
        budget = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        print(adzuna_bulk.run_recency_refresh(SessionLocal, call_budget=budget))
    elif mode == "aggregator_fallback":
        # keep collecting via Careerjet + Jooble when Adzuna is rate-limited
        print(aggregator_fallback.run_aggregator_fallback(SessionLocal))
    elif mode == "adzuna_status":
        import json
        with SessionLocal() as db:
            print(json.dumps(adzuna_bulk.status(db), indent=2, ensure_ascii=False))
    elif mode == "adzuna_board":
        out = sys.argv[2] if len(sys.argv) > 2 else "adzuna_board.html"
        with SessionLocal() as db:
            html = adzuna_bulk.render_board(adzuna_bulk.status(db))
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"wrote {out}")
    elif mode == "ingest":
        with SessionLocal() as db:
            print(run_ingest(db))
    else:
        with SessionLocal() as db:
            print(run_daily_digest(db, jobtiger_limit=20))
