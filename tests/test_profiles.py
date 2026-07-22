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
    assert "covered" in body                  # covered count chip
    assert "to check" in body                 # calm warning chip instead of loud red chips
    assert "CI/CD" in body                    # full missing text inside the expandable panel


def test_gaps_collapsed_with_full_text_in_panel(auth_client):
    # Owner feedback: red chips were too intrusive. Collapsed summary by default; the full
    # requirement sentences live inside the expandable details panel, tidy and complete.
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin", min_match=0)
    long_req = ("Familiarity with Go for backend development and understanding of Linux "
                "internals such as processes and memory management")
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Acme",
                      "description": f"Requirements:\n- Kotlin experience\n- {long_req}"})
    body = client.get(f"/profiles/{pid}").text
    assert "<details class='gaps'>" in body            # collapsed by default
    assert "chip warn" in body and "to check" in body  # calm ⚠ summary chip
    assert f"<li>{long_req}</li>" in body              # full text, tidy list in the panel
    assert "Not in your profile" in body


def test_nice_to_haves_get_advantage_subheading(auth_client):
    # Dimmer nice-to-have bullets confused the owner — they now sit under their own
    # "Considered an advantage" subheading, below the must-have gaps.
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin", min_match=0)
    jd = ("Requirements:\n- Kotlin experience\n- Rust experience\n"
          "Nice to have:\n- GraphQL experience")
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Acme", "description": jd})
    body = client.get(f"/profiles/{pid}").text
    assert "Considered an advantage" in body
    assert "<li class='nice'>GraphQL experience</li>" in body
    # musts stay in the main list, before the subheading
    assert body.index("Rust experience") < body.index("Considered an advantage")


def test_no_advantage_subheading_without_nice_gaps(auth_client):
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin", min_match=0)
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Acme",
                      "description": "Requirements:\n- Kotlin experience\n- Rust experience"})
    body = client.get(f"/profiles/{pid}").text
    assert "Not in your profile" in body
    assert "Considered an advantage" not in body


def test_match_card_shows_source_host(auth_client):
    # Owner feedback: 'everything comes from dev.bg' — every card now names its source site.
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin", min_match=0)
    client.post(f"/profiles/{pid}/postings",
                data={"title": "Role", "company": "Acme", "url": "https://dev.bg/company/x/job/1",
                      "description": "Requirements:\n- Kotlin experience"})
    body = client.get(f"/profiles/{pid}").text
    assert "class='m source'" in body and "dev.bg" in body


def test_app_ui_switches_to_bulgarian(auth_client):
    client, _ = auth_client
    pid = make_profile(client, skills="Kotlin", min_match=0)
    client.get("/lang/bg")                      # sets the lang cookie
    body = client.get(f"/profiles/{pid}").text
    assert "Търси сега" in body                 # control strip
    assert "Съвпадения ≥" in body
    assert "Все още няма съвпадения над прага" in body
    form = client.get(f"/profiles/{pid}/edit").text
    assert "Умения (разделени със запетая)" in form
    assert "Изтрий профила" in form
    client.get("/lang/en")                      # back to English
    assert "Search now" in client.get(f"/profiles/{pid}").text


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
