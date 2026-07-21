"""Account: GDPR data export and account deletion (with cascade + confirmation)."""
from tests.conftest import register, make_profile


def test_export_returns_user_and_profiles(auth_client):
    client, email = auth_client
    make_profile(client, name="Exported")
    r = client.get("/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    data = r.json()
    assert data["user"]["email"] == email
    assert [p["name"] for p in data["profiles"]] == ["Exported"]
    assert "applications" in data


def test_delete_requires_matching_email(auth_client):
    client, _ = auth_client
    make_profile(client)
    r = client.post("/account/delete", data={"confirm_email": "wrong@x.com"},
                    follow_redirects=True)
    assert "does not match" in r.text
    # still logged in and profile intact
    assert "No profiles yet" not in client.get("/").text


def test_delete_account_cascades_and_logs_out(client):
    email = register(client, email="del@test.local")
    make_profile(client, name="ToDelete")
    r = client.post("/account/delete", data={"confirm_email": email}, follow_redirects=False)
    assert r.status_code == 303
    # user is gone: cannot log back in
    client.cookies.clear()
    back = client.post("/login", data={"email": email, "password": "pw12345678"},
                       follow_redirects=True)
    assert "invalid credentials" in back.text.lower()


def test_delete_email_case_insensitive(client):
    email = register(client, email="case@test.local")
    r = client.post("/account/delete", data={"confirm_email": email.upper()},
                    follow_redirects=False)
    assert r.status_code == 303  # matching is case-insensitive
