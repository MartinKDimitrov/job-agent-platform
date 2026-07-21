"""Auth: register, login, logout, protection, OAuth-unconfigured behaviour."""
import pytest

from app.routers import auth as auth_module
from app.models import User
from app.db import SessionLocal
from sqlalchemy import select
from tests.conftest import register


def test_register_sets_cookie_and_redirects(client):
    r = client.post("/register", data={"email": "a@test.local", "password": "pw12345678"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "token" in r.cookies


def test_duplicate_email_rejected(client):
    register(client, email="dup@test.local")
    client.cookies.clear()
    r = client.post("/register", data={"email": "dup@test.local", "password": "x1234567"},
                    follow_redirects=True)
    assert "already registered" in r.text.lower()


def test_login_valid_and_invalid(client):
    register(client, email="li@test.local", password="rightpass1")
    client.cookies.clear()
    bad = client.post("/login", data={"email": "li@test.local", "password": "wrongpass"},
                      follow_redirects=True)
    assert "invalid credentials" in bad.text.lower()
    good = client.post("/login", data={"email": "li@test.local", "password": "rightpass1"},
                       follow_redirects=False)
    assert good.status_code == 303 and "token" in good.cookies


def test_logout_clears_cookie(client):
    register(client)
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    # After logout the dashboard shows the logged-out landing page.
    home = client.get("/")
    assert "Get started" in home.text


def test_protected_route_redirects_when_anonymous(client):
    client.cookies.clear()
    r = client.get("/profiles/new", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


def test_password_over_72_bytes_does_not_crash(client):
    # Regression: passlib/bcrypt crashed on >72 bytes; bcrypt-direct caps it.
    long_pw = "x" * 200
    r = client.post("/register", data={"email": "long@test.local", "password": long_pw},
                    follow_redirects=False)
    assert r.status_code == 303


def test_google_oauth_unconfigured_message(client):
    r = client.get("/auth/google", follow_redirects=True)
    assert "not configured" in r.text.lower()


# ---- Google OAuth callback (mocked so we don't hit Google) ----
class _FakeGoogle:
    def __init__(self, userinfo):
        self._userinfo = userinfo

    async def authorize_access_token(self, request):
        return {"userinfo": self._userinfo}


class _FakeOAuth:
    def __init__(self, userinfo):
        self.google = _FakeGoogle(userinfo)


def _mock_oauth(monkeypatch, userinfo):
    monkeypatch.setattr(auth_module, "_oauth", _FakeOAuth(userinfo))


def test_oauth_callback_creates_new_user(client, monkeypatch):
    _mock_oauth(monkeypatch, {"email": "New.OAuth@Test.local", "name": "New", "sub": "g-1"})
    r = client.get("/auth/google/callback", follow_redirects=False)
    assert r.status_code == 303 and "token" in r.cookies
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.email == "new.oauth@test.local")).scalar_one()
        assert u.google_sub == "g-1" and u.password_hash is None  # OAuth user has no password


def test_oauth_callback_reuses_existing_user(client, monkeypatch):
    register(client, email="both@test.local")           # user already exists (password account)
    client.cookies.clear()
    _mock_oauth(monkeypatch, {"email": "both@test.local", "name": "B", "sub": "g-2"})
    r = client.get("/auth/google/callback", follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        n = db.execute(select(User).where(User.email == "both@test.local")).scalars().all()
        assert len(n) == 1  # no duplicate account created


def test_oauth_callback_without_email_goes_to_login(client, monkeypatch):
    _mock_oauth(monkeypatch, {"name": "No Email"})       # provider returned no email
    r = client.get("/auth/google/callback", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")
    assert "token" not in r.cookies
