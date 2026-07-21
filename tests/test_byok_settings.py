"""BYOK settings: encrypted keystore + Account UI flow (provider mocked — hermetic)."""
from sqlalchemy import select

from app.data.db import SessionLocal
from app.data.keystore import encrypt_key, decrypt_key, save_config, get_config, delete_config
from app.data.llm import LLMError
from app.data.llm.base import ProviderInfo, register
from app.data.models import User, UserLLMConfig
from tests.conftest import register as register_user

KEY = "sk-live-VERYSECRET"


def _user(db, email="k@test.local"):
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u)
    return u


# ---- keystore unit ----
def test_encrypt_decrypt_roundtrip():
    token = encrypt_key(KEY)
    assert token and token != KEY and KEY not in token   # encrypted at rest
    assert decrypt_key(token) == KEY
    assert encrypt_key("") == "" and decrypt_key("") == ""
    assert decrypt_key("garbage-token") == ""            # corrupted -> treated as no key


def test_save_get_delete_config():
    with SessionLocal() as db:
        u = _user(db)
        save_config(db, u.id, "gemini", KEY, model="gemini-2.5-flash")
        # at rest: encrypted
        row = db.get(UserLLMConfig, u.id)
        assert KEY not in row.encrypted_key
        # decrypted on read
        cfg = get_config(db, u.id)
        assert cfg == {"provider": "gemini", "api_key": KEY, "model": "gemini-2.5-flash"}
        # overwrite
        save_config(db, u.id, "groq", "other-key")
        assert get_config(db, u.id)["provider"] == "groq"
        delete_config(db, u.id)
        assert get_config(db, u.id) is None


# ---- Account UI flow (fake provider so no network) ----
def _fake_provider(monkeypatch, fail=False, name="fakeprov", needs_key=True):
    def gen(system, prompt, api_key="", model=""):
        if fail:
            raise LLMError("Provider rejected the API key — test failure.")
        return "OK"
    register(ProviderInfo(name=name, label="Fake", needs_key=needs_key,
                          default_model="fake-1", generate=gen))


def test_save_flow_success(auth_client, monkeypatch):
    client, _ = auth_client
    _fake_provider(monkeypatch)
    r = client.post("/account/llm",
                    data={"provider": "fakeprov", "api_key": KEY, "model": ""},
                    follow_redirects=True)
    assert "Connection test passed" in r.text
    assert "Configured: <b>Fake</b>" in r.text
    assert KEY not in r.text                             # key never rendered back
    with SessionLocal() as db:
        row = db.execute(select(UserLLMConfig)).scalars().one()
        assert KEY not in row.encrypted_key              # stored encrypted


def test_save_flow_bad_key_not_stored(auth_client, monkeypatch):
    client, _ = auth_client
    _fake_provider(monkeypatch, fail=True, name="failprov")
    r = client.post("/account/llm",
                    data={"provider": "failprov", "api_key": "bad"}, follow_redirects=True)
    assert "rejected the API key" in r.text
    with SessionLocal() as db:
        assert db.execute(select(UserLLMConfig)).scalars().all() == []   # nothing saved


def test_keyless_provider_requires_no_key(auth_client, monkeypatch):
    client, _ = auth_client
    _fake_provider(monkeypatch, name="localprov", needs_key=False)
    r = client.post("/account/llm", data={"provider": "localprov", "api_key": ""},
                    follow_redirects=True)
    assert "Connection test passed" in r.text


def test_missing_key_for_keyed_provider(auth_client, monkeypatch):
    client, _ = auth_client
    _fake_provider(monkeypatch, name="needskey")
    r = client.post("/account/llm", data={"provider": "needskey", "api_key": ""},
                    follow_redirects=True)
    assert "requires an API key" in r.text


def test_delete_key(auth_client, monkeypatch):
    client, _ = auth_client
    _fake_provider(monkeypatch, name="delprov")
    client.post("/account/llm", data={"provider": "delprov", "api_key": KEY})
    r = client.post("/account/llm/delete", follow_redirects=True)
    assert "Key removed" in r.text
    with SessionLocal() as db:
        assert db.execute(select(UserLLMConfig)).scalars().all() == []


def test_unknown_provider_rejected(auth_client):
    client, _ = auth_client
    r = client.post("/account/llm", data={"provider": "nope", "api_key": "x"},
                    follow_redirects=True)
    assert "Unknown provider" in r.text
