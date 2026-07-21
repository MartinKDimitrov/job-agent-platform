"""Auth: register, login, logout, protection, OAuth-unconfigured behaviour."""
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
