"""LLM coverage verification: prompt/parse units, correction flow, budget, best-effort."""
import json

from sqlalchemy import select

import app.application.usecases.search as crawl
from app.application.usecases.verify_coverage import verify_match, verify_top_matches, _llm_for
from app.core.config import settings
from app.data.db import SessionLocal
from app.data.keystore import save_config
from app.data.llm import LLMError
from app.data.llm.base import ProviderInfo, register
from app.data.models import Match, Posting, User, Profile
from app.domain.prompts.verify_v1 import build_verify_prompt, parse_verify_response


class P:
    target_roles = "Android Developer"
    skills = "Kotlin, REST API"
    experience = "8 years mobile"
    languages = "Bulgarian, English"
    english_level = "A2"


REQS = [{"text": "Kotlin experience", "kind": "must"},
        {"text": "Practical experience with GraphQL APIs", "kind": "must"},
        {"text": "Fluent in English", "kind": "must"}]


# ---- prompt / parse units ----
def test_prompt_contains_profile_and_numbered_reqs():
    system, user = build_verify_prompt(P(), REQS)
    assert "treat every listed skill as TRUE" in system and '"covered"' in system
    assert "Kotlin, REST API" in user and "English level: A2" in user
    assert "1. [must] Kotlin experience" in user
    assert "3. [must] Fluent in English" in user


def test_parse_valid_partial_and_garbage():
    assert parse_verify_response('{"covered": [1, 3]}', 3) == {0, 2}
    assert parse_verify_response('Sure! {"covered": [2]} hope that helps', 3) == {1}
    assert parse_verify_response('{"covered": [7]}', 3) == set()   # out of range ignored
    assert parse_verify_response("I think the candidate is great", 3) is None
    assert parse_verify_response('{"other": 1}', 3) is None
    assert parse_verify_response("", 3) is None


# ---- correction flow ----
def _verify_provider(name, answer=None, fail=False):
    def gen(system, prompt, api_key="", model=""):
        if fail:
            raise LLMError("down")
        return answer
    register(ProviderInfo(name=name, label="V", needs_key=True,
                          default_model="v-1", generate=gen))


def _setup(db, provider, covered, missing, score=70):
    u = User(email="v@test.local", password_hash="x")
    db.add(u); db.commit(); db.refresh(u)
    p = Profile(user_id=u.id, name="P", target_roles="Android Developer",
                skills="Kotlin, REST API", english_level="A2", min_match=0)
    post = Posting(title="Role", company="Acme", url="https://x/1", apply_url="https://x/1",
                   description="d", content_hash="v1")
    db.add_all([p, post]); db.commit(); db.refresh(p); db.refresh(post)
    m = Match(profile_id=p.id, posting_id=post.id, score=score,
              covered=covered, missing=missing)
    db.add(m); db.commit(); db.refresh(m)
    save_config(db, u.id, provider, "sk-v")
    return u, p, post, m


def test_verify_moves_false_positives_and_rescored():
    # token scoring wrongly covered GraphQL (via 'api') and English (via 'english') —
    # the LLM keeps only Kotlin -> both move to missing, the score drops.
    _verify_provider("vprov", answer='{"covered": [1]}')
    with SessionLocal() as db:
        u, p, post, m = _setup(db, "vprov",
                               covered=[REQS[0], REQS[1], REQS[2]],
                               missing=[{"text": "Team player", "kind": "soft"}])
        old_score = m.score
        assert verify_match(db, p, m, post, _llm_for(db, u.id)) is True
        assert m.llm_verified is True
        assert [r["text"] for r in m.covered] == ["Kotlin experience"]
        assert "Practical experience with GraphQL APIs" in [r["text"] for r in m.missing]
        assert "Fluent in English" in [r["text"] for r in m.missing]
        # soft item stayed where it was (missing), untouched by the verifier
        assert {"text": "Team player", "kind": "soft"} in m.missing
        assert m.score < old_score
        assert m.score == round((1 / 3) * 100)                # kw=1/3, no vectors -> blend=kw


def test_unparseable_answer_leaves_match_untouched():
    _verify_provider("vbad", answer="cannot help with that")
    with SessionLocal() as db:
        u, p, post, m = _setup(db, "vbad", covered=[REQS[0]], missing=[REQS[1]])
        assert verify_match(db, p, m, post, _llm_for(db, u.id)) is False
        assert m.llm_verified is False and m.score == 70


def test_provider_error_is_best_effort():
    _verify_provider("vdown", fail=True)
    with SessionLocal() as db:
        u, p, post, m = _setup(db, "vdown", covered=[REQS[0]], missing=[])
        assert verify_match(db, p, m, post, _llm_for(db, u.id)) is False
        assert m.llm_verified is False


def test_top_matches_budget_and_caching(monkeypatch):
    calls = []
    def gen(system, prompt, api_key="", model=""):
        calls.append(1)
        return '{"covered": [1]}'
    register(ProviderInfo(name="vbudget", label="V", needs_key=True,
                          default_model="v-1", generate=gen))
    with SessionLocal() as db:
        u, p, post, m = _setup(db, "vbudget", covered=[REQS[0]], missing=[REQS[1]])
        for i in range(3):                        # more matches on extra postings
            extra = Posting(title=f"R{i}", company="Acme", url=f"https://x/e{i}",
                            apply_url=f"https://x/e{i}", description="d", content_hash=f"e{i}")
            db.add(extra); db.commit(); db.refresh(extra)
            db.add(Match(profile_id=p.id, posting_id=extra.id, score=60,
                         covered=[REQS[0]], missing=[]))
        db.commit()
        res = verify_top_matches(db, p, top_n=2)
        assert res["verified"] == 2 and len(calls) == 2       # budget respected
        res2 = verify_top_matches(db, p, top_n=10)
        assert res2["verified"] == 2                          # the rest, no re-verification
        assert verify_top_matches(db, p, top_n=0) == {"verified": 0, "failed": 0}


def test_no_provider_configured_is_silent():
    with SessionLocal() as db:
        u = User(email="np@test.local", password_hash="x")
        db.add(u); db.commit(); db.refresh(u)
        p = Profile(user_id=u.id, name="P", target_roles="X", min_match=0)
        db.add(p); db.commit(); db.refresh(p)
        assert verify_top_matches(db, p) == {"verified": 0, "failed": 0}


def test_feed_shows_ai_checked_badge(auth_client, monkeypatch):
    from tests.test_crawl import _mock
    from tests.conftest import make_profile
    _mock(monkeypatch)
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin, Compose", min_match=0)
    with SessionLocal() as db:
        crawl.ingest_from_sources(db)
    client.post(f"/profiles/{pid}/search", follow_redirects=False)
    assert "AI-checked" not in client.get(f"/profiles/{pid}").text
    with SessionLocal() as db:
        m = db.execute(select(Match)).scalars().first()
        m.llm_verified = True
        db.commit()
    assert "AI-checked" in client.get(f"/profiles/{pid}").text
