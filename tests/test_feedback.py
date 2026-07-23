"""Phase 6 feedback loop: apply-redirect + hide events, first-shown stamping, and the
score-breakdown / unused-skills transparency on match cards."""
import json

from sqlalchemy import select

from app.data.db import SessionLocal
from app.data.models import FeedbackEvent, Match, Posting
from tests.conftest import make_profile

JD = "Requirements:\n- Kotlin and Compose experience\n- CI/CD pipelines"


def _make_match(client, pid, title="Android Dev", url="https://ex.com/j1"):
    # follow_redirects=False: following the redirect renders the feed, which would already
    # stamp first_shown_at — the stamping test needs a never-rendered match
    client.post(f"/profiles/{pid}/postings",
                data={"title": title, "company": "Acme", "url": url,
                      "apply_url": url, "description": JD},
                follow_redirects=False)
    with SessionLocal() as db:
        m = db.execute(select(Match).where(Match.profile_id == pid)).scalars().first()
        return m.id


def test_apply_go_logs_event_and_redirects(auth_client):
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin, Compose")
    mid = _make_match(client, pid)
    r = client.get(f"/profiles/{pid}/matches/{mid}/go", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://ex.com/j1"
    with SessionLocal() as db:
        ev = db.execute(select(FeedbackEvent)).scalars().all()
        assert len(ev) == 1 and ev[0].event == "applied" and ev[0].profile_id == pid


def test_go_is_per_user(auth_client, client):
    owner, _ = auth_client
    pid = make_profile(owner, skills="Kotlin")
    mid = _make_match(owner, pid)
    from tests.conftest import register
    register(client, email="other@test.local")
    r = client.get(f"/profiles/{pid}/matches/{mid}/go", follow_redirects=False)
    assert r.headers["location"] == "/"                       # not their match — no redirect out
    with SessionLocal() as db:
        assert db.execute(select(FeedbackEvent)).scalars().all() == []


def test_hide_removes_from_feed_and_logs(auth_client):
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin, Compose")
    mid = _make_match(client, pid, title="Hide Me")
    assert "Hide Me" in client.get(f"/profiles/{pid}").text
    r = client.post(f"/profiles/{pid}/matches/{mid}/hide", follow_redirects=False)
    assert r.status_code == 303
    assert "Hide Me" not in client.get(f"/profiles/{pid}").text
    with SessionLocal() as db:
        assert db.get(Match, mid).hidden is True
        ev = db.execute(select(FeedbackEvent)).scalars().all()
        assert len(ev) == 1 and ev[0].event == "hidden"


def test_first_shown_stamped_once_on_render(auth_client):
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin, Compose")
    mid = _make_match(client, pid)
    with SessionLocal() as db:
        assert db.get(Match, mid).first_shown_at is None      # created, never rendered
    client.get(f"/profiles/{pid}")
    with SessionLocal() as db:
        first = db.get(Match, mid).first_shown_at
        assert first is not None
    client.get(f"/profiles/{pid}")                            # re-render must not move it
    with SessionLocal() as db:
        assert db.get(Match, mid).first_shown_at == first


def test_card_shows_breakdown_and_unused_skills(auth_client):
    client, _ = auth_client
    # Python is in the profile but nowhere in the posting -> the muted 'unused' chip
    pid = make_profile(client, skills="Kotlin, Compose, Python")
    _make_match(client, pid)
    body = client.get(f"/profiles/{pid}").text
    assert "requirements" in body                             # coverage component line
    assert "not asked for here" in body
    assert ">python</span>" in body


def test_annotate_counts_unknown_skills(monkeypatch):
    from app.core.config import settings
    from app.application.usecases.annotate import annotate_postings
    from tests.test_annotate import _post, _provider
    answer = json.dumps({"annotations": [
        {"n": 1, "skills": ["kotlin", "quantum-flux"], "weight": 4},
        {"n": 2, "skills": ["java"], "weight": 1}]})
    _provider("unkprov", answer=answer)
    monkeypatch.setattr(settings, "server_llm_provider", "unkprov")
    monkeypatch.setattr(settings, "annotate_budget", 5)
    with SessionLocal() as db:
        _post(db, chash="unk1")
        res = annotate_postings(db, delay=0)
        assert res["annotated"] == 1
        assert res["unknown_skills"] == 1                     # quantum-flux isn't in skills-v1
