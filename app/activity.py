"""Per-user activity: last-seen tracking + the "I found a job" pause, used to decide who the
daily job searches for. We don't waste crawl/scoring on users who found a job or went inactive.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import UserActivity

_TOUCH_THROTTLE = timedelta(hours=1)   # don't write on every request
ACTIVE_DAYS = 5                        # searched only if seen within this many days


def touch(db: Session, user_id: int) -> None:
    """Record that we just saw this user (throttled, so it's cheap on hot paths)."""
    now = datetime.utcnow()
    act = db.get(UserActivity, user_id)
    if act is None:
        db.add(UserActivity(user_id=user_id, last_seen_at=now))
        db.commit()
    elif act.last_seen_at is None or now - act.last_seen_at > _TOUCH_THROTTLE:
        act.last_seen_at = now
        db.commit()


def get_activity(db: Session, user_id: int) -> UserActivity | None:
    return db.get(UserActivity, user_id)


def set_found_job(db: Session, user_id: int, value: bool) -> None:
    act = db.get(UserActivity, user_id)
    if act is None:
        act = UserActivity(user_id=user_id, last_seen_at=datetime.utcnow())
        db.add(act)
    act.found_job = value
    db.commit()


def is_active_for_search(user, act: UserActivity | None, now: datetime | None = None,
                         days: int = ACTIVE_DAYS) -> bool:
    """True if the daily job should search for this user: not paused (found a job) and seen
    within `days`. New users with no activity row yet fall back to their signup date."""
    now = now or datetime.utcnow()
    if act and act.found_job:
        return False
    last = (act.last_seen_at if act else None) or user.created_at
    return last is not None and (now - last) <= timedelta(days=days)
