"""Shared test fixtures.

Tests are hermetic and do NOT need the SSH tunnel: we point the app at a throwaway SQLite
file (via the DATABASE_URL env var, read before the app imports), rebuild the schema before
every test, and force the keyword scoring path so nothing downloads an embedding model.
"""
import os
import tempfile

# Must be set before importing anything under `app` — settings/engine are built at import time.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["SECRET_KEY"] = "test-secret-key"
# Keep tests hermetic: never inherit real Google OAuth creds from a local .env. Callback tests
# inject a fake _oauth explicitly; everything else should see OAuth as unconfigured.
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
# The in-app background ingester fetches REAL sources — a local .env with INGEST_EVERY_HOURS=6
# would make TestClient app startup spawn it and hang the suite on live network calls.
os.environ["INGEST_EVERY_HOURS"] = "0"
# The takedown probe GETs real posting URLs (dev.bg...) — never from tests.
os.environ["TAKEDOWN_PROBE_BUDGET"] = "0"
# A local .env with the platform's free-lane LLM key would make tests call the REAL
# provider (generation and coverage verification) — force the lane off.
os.environ["SERVER_LLM_PROVIDER"] = ""
os.environ["SERVER_LLM_API_KEY"] = ""

import pytest
from sqlalchemy import event
from fastapi.testclient import TestClient

from app.data.db import engine, Base, SessionLocal
from app.data import models  # noqa: F401  (register models on Base)
from app.main import app
import app.domain.scoring as scoring


# SQLite enforces ON DELETE CASCADE only when this pragma is on — needed to test cascades.
@event.listens_for(engine, "connect")
def _sqlite_fk_pragma(dbapi_con, _record):
    dbapi_con.execute("PRAGMA foreign_keys=ON")


@pytest.fixture(autouse=True)
def fresh_db():
    """Give every test an empty schema (and a cold recall cache — it is process-global)."""
    from app.application import vector_cache
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    vector_cache.invalidate()
    yield


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    """Keep scoring deterministic and fast: force the weighted-keyword path (no model load)."""
    monkeypatch.setattr(scoring, "embed", lambda text, prefix="query: ": None)


@pytest.fixture
def client():
    """TestClient; entering it runs startup -> init_db() which seeds built-in sources."""
    with TestClient(app) as c:
        yield c


def register(client, email="user@test.local", password="pw12345678", name="U"):
    """Register (and thereby log in) a user; returns the email. Cookie stays in the jar."""
    r = client.post("/register", data={"email": email, "password": password, "name": name},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    return email


def make_profile(client, name="Android", skills="Kotlin, Compose", min_match=0, **extra):
    data = {"name": name, "target_roles": extra.get("target_roles", "Android"),
            "skills": skills, "english_level": extra.get("english_level", "B2"),
            "remote_pref": extra.get("remote_pref", "remote"),
            "min_match": str(min_match)}
    data.update({k: v for k, v in extra.items() if k not in data})
    r = client.post("/profiles", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[-1])


@pytest.fixture
def auth_client(client):
    """Client with a registered, logged-in user."""
    email = register(client)
    return client, email
