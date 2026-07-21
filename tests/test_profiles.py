"""Profiles: create/validate/edit/delete, per-user isolation, scoring view, threshold tuner."""
from tests.conftest import register, make_profile


def test_create_valid_profile_appears_on_dashboard(auth_client):
    client, _ = auth_client
    make_profile(client, name="Senior Android")
    assert "Senior Android" in client.get("/").text


def test_create_invalid_profile_shows_errors(auth_client):
    client, _ = auth_client
    r = client.post("/profiles", data={"name": "", "english_level": "ZZ",
                                       "remote_pref": "remote", "min_match": "250"},
                    follow_redirects=True)
    assert "Please fix" in r.text
    assert "name is required" in r.text.lower()
    assert "between 0 and 100" in r.text
    assert "English level" in r.text
    # nothing was created
    assert "No profiles yet" in client.get("/").text


def test_edit_form_is_prefilled(auth_client):
    client, _ = auth_client
    pid = make_profile(client, name="Android Lead")
    body = client.get(f"/profiles/{pid}/edit").text
    assert 'value="Android Lead"' in body


def test_update_changes_values(auth_client):
    client, _ = auth_client
    pid = make_profile(client, name="Android Lead", min_match=0)
    r = client.post(f"/profiles/{pid}/edit",
                    data={"name": "Android Staff", "english_level": "C1",
                          "remote_pref": "hybrid", "min_match": "80"},
                    follow_redirects=False)
    assert r.status_code == 303
    body = client.get(f"/profiles/{pid}").text
    assert "Android Staff" in body and "min 80%" in body


def test_delete_profile(auth_client):
    client, _ = auth_client
    pid = make_profile(client)
    r = client.post(f"/profiles/{pid}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert "No profiles yet" in client.get("/").text


def test_min_match_tuner_updates_and_filters(auth_client):
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin, Compose", min_match=0)
    # add a posting that will score < 100 (CI/CD is missing)
    jd = "Requirements:\n- Kotlin and Compose\n- CI/CD pipelines"
    client.post(f"/profiles/{pid}/postings",
                data={"title": "X", "company": "Y", "description": jd})
    assert "X" in client.get(f"/profiles/{pid}").text          # visible at threshold 0
    client.post(f"/profiles/{pid}/min_match", data={"min_match": "99"})
    body = client.get(f"/profiles/{pid}").text
    assert "min 99%" in body and "No matches above threshold" in body


def test_scoring_view_shows_gaps_as_chips(auth_client):
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin, Compose", min_match=0)
    jd = "Requirements:\n- Kotlin and Compose\n- CI/CD pipelines"
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Co", "description": jd})
    body = client.get(f"/profiles/{pid}").text
    assert "covered" in body                 # green covered count
    assert "CI/CD" in body                    # missing must-have chip


def test_min_match_clamped(auth_client):
    client, _ = auth_client
    pid = make_profile(client, min_match=0)
    client.post(f"/profiles/{pid}/min_match", data={"min_match": "500"})
    assert "min 100%" in client.get(f"/profiles/{pid}").text


# ---- per-user isolation ----
def test_cannot_view_or_mutate_another_users_profile(client):
    register(client, email="owner@test.local")
    pid = make_profile(client, name="Owner Profile")
    # switch to a different user (register logs them in, replacing the cookie)
    register(client, email="intruder@test.local")
    assert "Not found" in client.get(f"/profiles/{pid}").text
    # mutation attempts must not change anything
    client.post(f"/profiles/{pid}/edit",
                data={"name": "Hacked", "english_level": "B2", "remote_pref": "remote",
                      "min_match": "0"}, follow_redirects=False)
    client.post(f"/profiles/{pid}/delete", follow_redirects=False)
    # back to the owner: profile is intact
    register(client, email="owner@test.local") if False else client.post(
        "/login", data={"email": "owner@test.local", "password": "pw12345678"})
    body = client.get(f"/profiles/{pid}").text
    assert "Owner Profile" in body and "Hacked" not in body
