"""Document generation: prompt templates (pure), use case, and routes (provider mocked)."""
import pytest
from sqlalchemy import select

from app.data.db import SessionLocal
from app.data.keystore import save_config
from app.data.llm import LLMError
from app.data.llm.base import ProviderInfo, register
from app.data.models import User, Profile, Posting, Match, Document
from app.domain.prompts import PROMPT_VERSION, build_cv_prompt, build_cover_letter_prompt
from app.application.usecases.generate_document import generate_document, GenerationError
from tests.conftest import register as register_user, make_profile


class P:
    """Profile stand-in for prompt unit tests."""
    target_roles = "Android Developer"
    skills = "Kotlin, Compose"
    experience = "10 years mobile"
    languages = "Bulgarian, English"
    english_level = "B1"
    location_pref = "Varna"


class Post:
    title = "Senior Android Engineer"
    company = "Acme"
    location = "Remote"
    description = "x" * 2000
    requirements = [{"text": "Kotlin", "kind": "must"}, {"text": "KMP", "kind": "nice"}]


# ---- prompt templates (pure) ----
def test_cv_prompt_contains_structure_and_constraints():
    system, user = build_cv_prompt(P(), Post(), covered=[{"text": "Kotlin"}],
                                   missing=[{"text": "KMP"}], lang="en")
    assert "B1" in system                           # CEFR level enforced
    assert "Never invent" in system                 # honesty rule
    assert "Kotlin, Compose" in user                # structured profile data
    assert "- Kotlin" in user and "- KMP" in user   # structured requirements by kind
    assert "does NOT cover" in user and "KMP" in user
    assert len(user) < 3500                         # description capped (token cost = user money)


def test_cover_letter_prompt_bg_language():
    system, _user = build_cover_letter_prompt(P(), Post(), lang="bg")
    assert "Bulgarian" in system
    system_en, _ = build_cover_letter_prompt(P(), Post(), lang="en")
    assert "English" in system_en


# ---- use case ----
def _fake_provider(name="genprov", fail=False):
    def gen(system, prompt, api_key="", model=""):
        if fail:
            raise LLMError("Provider exploded.")
        return f"GENERATED[{model or 'default'}]"
    register(ProviderInfo(name=name, label="Gen", needs_key=True,
                          default_model="gen-1", generate=gen))


def _setup_db(db, provider="genprov", with_config=True):
    u = User(email="g@test.local", password_hash="x")
    db.add(u); db.commit(); db.refresh(u)
    p = Profile(user_id=u.id, name="P", target_roles="Android", skills="Kotlin",
                english_level="B2", min_match=0)
    post = Posting(title="Role", company="Acme", description="Requirements:\n- Kotlin",
                   requirements=[{"text": "Kotlin", "kind": "must"}],
                   apply_url="https://x/1", content_hash="h1")
    db.add_all([p, post]); db.commit(); db.refresh(p); db.refresh(post)
    db.add(Match(profile_id=p.id, posting_id=post.id, score=80,
                 covered=[{"text": "Kotlin", "kind": "must"}], missing=[]))
    db.commit()
    if with_config:
        save_config(db, u.id, provider, "sk-key")
    return u, p, post


def test_generate_document_success():
    _fake_provider()
    with SessionLocal() as db:
        u, p, post = _setup_db(db)
        doc = generate_document(db, u, p.id, post.id, kind="cv", lang="en")
        assert doc.content.startswith("GENERATED")
        assert doc.provider == "genprov" and doc.prompt_version == PROMPT_VERSION
        assert doc.kind == "cv" and doc.lang == "en"


def test_generate_without_config_readable_error():
    _fake_provider()
    with SessionLocal() as db:
        u, p, post = _setup_db(db, with_config=False)
        with pytest.raises(GenerationError, match="Account"):
            generate_document(db, u, p.id, post.id)


def test_generate_provider_failure_propagates_readably():
    _fake_provider(name="failgen", fail=True)
    with SessionLocal() as db:
        u, p, post = _setup_db(db, provider="failgen")
        with pytest.raises(GenerationError, match="exploded"):
            generate_document(db, u, p.id, post.id)
        assert db.execute(select(Document)).scalars().all() == []   # nothing stored on failure


def test_generate_foreign_profile_rejected():
    _fake_provider()
    with SessionLocal() as db:
        u, p, post = _setup_db(db)
        intruder = User(email="i@test.local", password_hash="x")
        db.add(intruder); db.commit(); db.refresh(intruder)
        save_config(db, intruder.id, "genprov", "sk-2")
        with pytest.raises(GenerationError, match="not found"):
            generate_document(db, intruder, p.id, post.id)


def test_invalid_kind_lang():
    _fake_provider()
    with SessionLocal() as db:
        u, p, post = _setup_db(db)
        with pytest.raises(GenerationError):
            generate_document(db, u, p.id, post.id, kind="poem")
        with pytest.raises(GenerationError):
            generate_document(db, u, p.id, post.id, lang="de")


# ---- routes ----
def test_generate_route_flow(auth_client):
    _fake_provider(name="routeprov")
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin", min_match=0)
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Acme",
                      "description": "Requirements:\n- Kotlin"})
    client.post("/account/llm", data={"provider": "routeprov", "api_key": "sk-x"})
    with SessionLocal() as db:
        post_id = db.execute(select(Posting.id)).scalar_one()
    r = client.post(f"/profiles/{pid}/postings/{post_id}/generate",
                    data={"kind": "cv", "lang": "en"}, follow_redirects=True)
    assert "GENERATED" in r.text and "Review and edit" in r.text
    # list page shows it
    assert "CV (EN)" in client.get("/documents").text


def test_generate_route_without_key_shows_error(auth_client):
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin", min_match=0)
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Acme",
                      "description": "Requirements:\n- Kotlin"})
    with SessionLocal() as db:
        post_id = db.execute(select(Posting.id)).scalar_one()
    r = client.post(f"/profiles/{pid}/postings/{post_id}/generate",
                    data={"kind": "cv"}, follow_redirects=True)
    assert "Generation failed" in r.text and "Account" in r.text


def test_document_view_is_owner_only(auth_client):
    _fake_provider(name="ownprov")
    client, _ = auth_client
    pid = make_profile(client, target_roles="Android", skills="Kotlin", min_match=0)
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Acme",
                      "description": "Requirements:\n- Kotlin"})
    client.post("/account/llm", data={"provider": "ownprov", "api_key": "sk-x"})
    with SessionLocal() as db:
        post_id = db.execute(select(Posting.id)).scalar_one()
    client.post(f"/profiles/{pid}/postings/{post_id}/generate", data={"kind": "cv"})
    with SessionLocal() as db:
        doc_id = db.execute(select(Document.id)).scalar_one()
    # switch user
    register_user(client, email="other@test.local")
    assert "Not found" in client.get(f"/documents/{doc_id}").text
