"""Requirement annotation (annotate-v1): prompt/parse, merge, invalidation, scoring effect."""
import json

from sqlalchemy import select

import app.application.usecases.annotate as ann
from app.application.usecases.annotate import annotate_posting, annotate_postings
from app.core.config import settings
from app.data.db import SessionLocal
from app.data.llm.base import ProviderInfo, register
from app.data.models import Posting
from app.domain.prompts.annotate_v1 import (ANNOTATE_VERSION, build_annotate_prompt,
                                            parse_annotate_response, requirements_fingerprint)
from app.domain.scoring import req_weight, requirement_hit, score

REQS = [{"text": "Proven experience building Android apps with Kotlin or Java", "kind": "must"},
        {"text": "Familiarity with XML layouts", "kind": "nice"},
        {"text": "Mentor junior engineers", "kind": "resp"}]

ANSWER = json.dumps({"annotations": [
    {"n": 1, "skills": ["kotlin", "java"], "weight": 5},
    {"n": 2, "skills": ["xml"], "weight": 1},
]})


# ---- prompt / parse ----
def test_prompt_numbers_only_scored_requirements():
    from app.domain.prompts.annotate_v1 import scored_requirements
    scored = scored_requirements(REQS)
    assert len(scored) == 2                                   # resp excluded
    system, user = build_annotate_prompt("Android Developer", scored)
    assert "ANY ONE" in system and '"annotations"' in system
    assert "1. Proven experience" in user and "2. Familiarity with XML" in user


def test_parse_valid_partial_garbage():
    parsed = parse_annotate_response(ANSWER, 2)
    assert parsed[0] == (["kotlin", "java"], 5) and parsed[1] == (["xml"], 1)
    partial = parse_annotate_response('{"annotations": [{"n": 2, "skills": ["xml"]}]}', 2)
    assert partial == {1: (["xml"], 3)}                        # default weight, partial ok
    assert parse_annotate_response("no json here", 2) is None
    assert parse_annotate_response('{"annotations": "nope"}', 2) is None
    assert parse_annotate_response('{"annotations": [{"n": 9, "skills": ["x"]}]}', 2) is None


def test_fingerprint_tracks_scored_texts():
    fp1 = requirements_fingerprint(REQS)
    assert fp1 == requirements_fingerprint(REQS + [{"text": "New duty", "kind": "resp"}])
    assert fp1 != requirements_fingerprint([{"text": "Different", "kind": "must"}])


# ---- annotation flow ----
def _provider(name, answer=ANSWER, fail=False):
    from app.data.llm import LLMError
    def gen(system, prompt, api_key="", model=""):
        if fail:
            raise LLMError("down")
        return answer
    register(ProviderInfo(name=name, label="A", needs_key=True,
                          default_model="a-1", generate=gen))


def _post(db, chash="a1", reqs=None):
    p = Posting(title="Android Developer", company="Acme", url=f"https://x/{chash}",
                apply_url=f"https://x/{chash}", description="d",
                requirements=reqs if reqs is not None else [dict(r) for r in REQS],
                content_hash=chash)
    db.add(p); db.commit(); db.refresh(p)
    return p


def test_annotate_posting_merges_skills_and_marks_version(monkeypatch):
    _provider("annprov")
    monkeypatch.setattr(settings, "server_llm_provider", "annprov")
    with SessionLocal() as db:
        p = _post(db)
        assert annotate_posting(db, p, ann._platform_llm()) is True
        db.commit()
        assert p.annotation_version == ANNOTATE_VERSION
        assert p.annotation_fp == requirements_fingerprint(p.requirements)
        must = p.requirements[0]
        assert must["skills"] == ["java", "kotlin"] and must["weight"] == 5  # canonized+sorted
        assert p.requirements[1]["weight"] == 1
        assert "skills" not in p.requirements[2]               # resp untouched


def test_annotate_postings_budget_and_invalidation(monkeypatch):
    calls = []
    from app.data.llm import LLMError  # noqa: F401
    def gen(system, prompt, api_key="", model=""):
        calls.append(1)
        return ANSWER
    register(ProviderInfo(name="annb", label="A", needs_key=True,
                          default_model="a-1", generate=gen))
    monkeypatch.setattr(settings, "server_llm_provider", "annb")
    with SessionLocal() as db:
        for i in range(3):
            _post(db, chash=f"b{i}")
        res = annotate_postings(db, budget=2, delay=0, sleep=lambda s: None)
        assert res["annotated"] == 2 and len(calls) == 2       # budget respected
        res = annotate_postings(db, budget=10, delay=0, sleep=lambda s: None)
        assert res["annotated"] == 1                           # only the remaining one
        res = annotate_postings(db, budget=10, delay=0, sleep=lambda s: None)
        assert res["annotated"] == 0 and len(calls) == 3       # cached: no re-annotation
        # requirements change -> fingerprint mismatch -> re-annotated
        p = db.execute(select(Posting)).scalars().first()
        p.requirements = [{"text": "Completely new requirement text", "kind": "must"}]
        db.commit()
        res = annotate_postings(db, budget=10, delay=0, sleep=lambda s: None)
        assert res["annotated"] == 1 and len(calls) == 4


def test_annotate_no_platform_lane_is_silent():
    with SessionLocal() as db:
        _post(db, chash="c1")
        assert annotate_postings(db) == {"annotated": 0, "failed": 0}


def test_annotate_failure_left_for_retry(monkeypatch):
    _provider("anndown", fail=True)
    monkeypatch.setattr(settings, "server_llm_provider", "anndown")
    with SessionLocal() as db:
        p = _post(db, chash="d1")
        res = annotate_postings(db, budget=5, delay=0, sleep=lambda s: None)
        assert res["failed"] == 1 and p.annotation_version == ""


# ---- scoring with annotations ----
def test_requirement_hit_uses_canonical_skills():
    r = {"text": "Practical experience with GraphQL APIs", "kind": "must",
         "skills": ["graphql"], "weight": 4}
    # token overlap would wrongly cover via 'api'/'apis' — annotation says graphql only
    assert requirement_hit(r, "Android Developer · Kotlin, REST API") is False
    assert requirement_hit(r, "Backend · GraphQL, Node.js") is True
    # word boundaries: 'r' must not match inside 'runtime'
    assert requirement_hit({"text": "R", "kind": "must", "skills": ["r"]},
                           "runtime tooling") is False


def test_req_weight_scales_kind_by_importance():
    assert req_weight({"kind": "must", "weight": 5}) > req_weight({"kind": "must", "weight": 3})
    assert req_weight({"kind": "must"}) == 1.0                 # neutral default
    assert req_weight({"kind": "nice", "weight": 1}) < 0.2
    assert req_weight({"kind": "resp", "weight": 5}) == 0.0


def test_score_with_annotated_requirements():
    reqs = [{"text": "Kotlin experience", "kind": "must", "skills": ["kotlin"], "weight": 5},
            {"text": "XML layouts", "kind": "must", "skills": ["xml"], "weight": 1}]
    sc_kotlin, cov, mis = score("Android · Kotlin", "role", reqs)
    sc_xml, _, _ = score("Android · XML", "role", reqs)
    assert [c["text"] for c in cov] == ["Kotlin experience"]
    assert sc_kotlin > sc_xml                                  # ★★★★★ beats ★


def test_parse_tolerates_fences_and_trailing_commas():
    fenced = '```json\n{"annotations": [{"n": 1, "skills": ["kotlin"], "weight": 4},]}\n```'
    assert parse_annotate_response(fenced, 1) == {0: (["kotlin"], 4)}
