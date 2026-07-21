"""Sources: built-in list, user-added sources, per-user isolation."""
from tests.conftest import register


def test_builtin_sources_listed(auth_client):
    client, _ = auth_client
    body = client.get("/sources").text
    assert "Greenhouse (ATS)" in body and "LinkedIn" in body


def test_add_user_source(auth_client):
    client, _ = auth_client
    r = client.post("/sources", data={"name": "My Board", "url": "https://example.com"},
                    follow_redirects=True)
    assert "My Board" in r.text


def test_user_sources_are_isolated(client):
    register(client, email="a@test.local")
    client.post("/sources", data={"name": "A Private Board", "url": "https://a.example"})
    register(client, email="b@test.local")
    body = client.get("/sources").text
    assert "A Private Board" not in body          # B must not see A's source
    assert "Greenhouse (ATS)" in body             # but built-ins are shared
