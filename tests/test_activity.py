"""Per-user activity tracking + the 'I found a job' toggle."""
from sqlalchemy import select

from app.data.db import SessionLocal
from app.data.models import UserActivity


def test_authenticated_visit_records_activity(auth_client):
    client, _ = auth_client
    client.get("/")                       # an authenticated request
    with SessionLocal() as db:
        acts = db.execute(select(UserActivity)).scalars().all()
        assert len(acts) == 1 and acts[0].last_seen_at is not None


def test_found_job_toggle(auth_client):
    client, _ = auth_client
    r = client.post("/account/found-job", data={"value": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert "Paused" in client.get("/account").text
    client.post("/account/found-job", data={"value": "0"})
    assert "Active" in client.get("/account").text
