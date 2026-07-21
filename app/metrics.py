"""CLI entrypoint for crawl-run metrics: `python -m app.metrics` (composition root — the
logic lives in app/data/metrics_repo.py)."""
from .data.metrics_repo import summary, format_summary  # noqa: F401  (re-export)

if __name__ == "__main__":
    from .data.db import SessionLocal
    with SessionLocal() as db:
        print(format_summary(summary(db)))
