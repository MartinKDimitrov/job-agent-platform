"""Pure activity rules: should the daily job search for this user?

Domain logic only — takes plain objects (duck-typed user / activity rows), no DB access.
Persistence lives in app/data/activity_repo.py.
"""
from datetime import datetime, timedelta

ACTIVE_DAYS = 5  # searched only if seen within this many days


def is_active_for_search(user, act, now: datetime | None = None,
                         days: int = ACTIVE_DAYS) -> bool:
    """True if the daily job should search for this user: not paused ("I found a job") and seen
    within `days`. New users with no activity row yet fall back to their signup date.

    `user` needs `.created_at`; `act` (may be None) needs `.found_job` and `.last_seen_at`.
    """
    now = now or datetime.utcnow()
    if act is not None and act.found_job:
        return False
    last = (act.last_seen_at if act is not None else None) or user.created_at
    return last is not None and (now - last) <= timedelta(days=days)
