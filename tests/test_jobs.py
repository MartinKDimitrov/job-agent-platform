"""Daily digest job: per-user new matches, no re-notify, activity + found-job gating."""
from datetime import datetime, timedelta

from sqlalchemy import select

import app.adapters.greenhouse as gh
import app.adapters.dev_bg as dev_bg
from app.adapters.base import RawPosting
from app.jobs import run_daily_digest
from app.db import SessionLocal
from app.models import User, Profile, UserActivity, DigestEntry

BOARDS = [("acme", "Acme")]

SAMPLE = [
    RawPosting("ats_api", "1", "Senior Android Engineer", "Acme", location="Remote",
               url="https://x/1", apply_url="https://x/1",
               description="Requirements:\n- Kotlin and Compose"),
    RawPosting("ats_api", "2", "Android Engineering Manager", "Acme", location="Remote",
               url="https://x/2", apply_url="https://x/2", description="Requirements:\n- Kotlin"),
    RawPosting("ats_api", "3", "Sales Executive", "Acme", location="Remote",
               url="https://x/3", apply_url="https://x/3", description="Sales role"),
]


class Sender:
    def __init__(self):
        self.sent = []

    def __call__(self, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})
        return True


def _setup(monkeypatch):
    monkeypatch.setattr(gh, "fetch", lambda token, company_name=None: list(SAMPLE))
    monkeypatch.setattr(dev_bg, "fetch", lambda categories=None: [])   # keep tests offline


def _user(db, email, seen_days_ago=0, found_job=False, with_profile=True):
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u)
    db.add(UserActivity(user_id=u.id,
                        last_seen_at=datetime.utcnow() - timedelta(days=seen_days_ago),
                        found_job=found_job))
    if with_profile:
        db.add(Profile(user_id=u.id, name="P", target_roles="Android",
                       skills="Kotlin, Compose", min_match=0))
    db.commit()
    return u


def test_active_user_gets_digest_with_only_relevant_ic_role(monkeypatch):
    _setup(monkeypatch)
    send = Sender()
    with SessionLocal() as db:
        _user(db, "a@test.local")
        res = run_daily_digest(db, boards=BOARDS, send=send)
    assert res["notified"] == 1 and res["emails_sent"] == 1 and res["new_matches"] == 1
    html = send.sent[0]["html"]
    assert "Senior Android Engineer" in html
    assert "Engineering Manager" not in html          # filtered by seniority
    assert "Sales Executive" not in html              # filtered by keyword pre-filter
    assert "https://x/1" in html                      # apply link


def test_second_run_does_not_renotify(monkeypatch):
    _setup(monkeypatch)
    with SessionLocal() as db:
        _user(db, "b@test.local")
        run_daily_digest(db, boards=BOARDS, send=Sender())
        send2 = Sender()
        res2 = run_daily_digest(db, boards=BOARDS, send=send2)
    assert res2["notified"] == 0 and send2.sent == []


def test_inactive_user_skipped(monkeypatch):
    _setup(monkeypatch)
    send = Sender()
    with SessionLocal() as db:
        _user(db, "c@test.local", seen_days_ago=10)
        res = run_daily_digest(db, boards=BOARDS, send=send)
    assert res["skipped"] == 1 and res["notified"] == 0 and send.sent == []


def test_found_job_user_skipped(monkeypatch):
    _setup(monkeypatch)
    send = Sender()
    with SessionLocal() as db:
        _user(db, "d@test.local", found_job=True)
        res = run_daily_digest(db, boards=BOARDS, send=send)
    assert res["skipped"] == 1 and send.sent == []


def test_user_without_profile_not_notified(monkeypatch):
    _setup(monkeypatch)
    send = Sender()
    with SessionLocal() as db:
        _user(db, "e@test.local", with_profile=False)
        res = run_daily_digest(db, boards=BOARDS, send=send)
    assert res["notified"] == 0 and send.sent == []
