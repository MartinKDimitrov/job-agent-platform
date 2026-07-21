"""Persistence + reporting for crawl-run metrics (CrawlRun rows).

The in-memory collector (RunStats) lives in app/application/run_stats.py; this module only
stores and reads. `stats` parameters are duck-typed (anything with .to_dict()) so the data
layer doesn't depend on the application layer.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CrawlRun


def record_run(db: Session, kind: str, stats, started_at: datetime,
               ok: bool = True, error: str = "") -> CrawlRun:
    run = CrawlRun(kind=kind, started_at=started_at, finished_at=datetime.utcnow(),
                   ok=ok, error=(error or "")[:2000],
                   stats=stats.to_dict() if stats else None)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def summary(db: Session, last: int = 10) -> list[dict]:
    runs = db.execute(
        select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(last)).scalars().all()
    rows = []
    for r in runs:
        st = r.stats or {}
        rows.append({
            "id": r.id, "kind": r.kind, "started": r.started_at, "ok": r.ok,
            "totals": st.get("totals", {}),
            "sources": {k: v.get("fetched", 0) for k, v in (st.get("sources") or {}).items()},
            "error": r.error,
        })
    return rows


def format_summary(rows: list[dict]) -> str:
    if not rows:
        return "(no crawl runs recorded yet)"
    out = []
    for r in rows:
        t = r["totals"]
        out.append(
            f"#{r['id']} {r['kind']:10} {r['started']:%Y-%m-%d %H:%M} "
            f"{'OK ' if r['ok'] else 'ERR'} "
            f"matched={t.get('matched', 0)} notified={t.get('notified', 0)} "
            f"added={t.get('added', 0)} deduped={t.get('deduped', 0)} "
            f"filtered={t.get('filtered', 0)}")
        if r["sources"]:
            out.append("       sources: " + "  ".join(f"{k}={v}" for k, v in r["sources"].items()))
        if r["error"]:
            out.append(f"       error: {r['error'][:150]}")
    return "\n".join(out)
