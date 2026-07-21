"""Per-user activity persistence: last-seen tracking + the "I found a job" pause flag.
The decision rule (should the daily job search for this user?) is pure domain logic — see
app/domain/activity_rules.py."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import UserActivity

_TOUCH_THROTTLE = timedelta(hours=1)   # don't write on every request


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
