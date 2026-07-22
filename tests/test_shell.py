"""Page-shell chrome: ripple + full-screen loading overlay ship on every page."""


def test_shell_has_loading_overlay_and_ripple(client):
    body = client.get("/").text
    assert 'id="loading-overlay"' in body
    assert 'class="spinner"' in body
    assert ".btn, .profile-tabs .tab" in body      # ripple delegate
    assert 'addEventListener("submit"' in body     # overlay on server round-trips
    assert "pageshow" in body                      # bfcache back-nav hides it


def test_overlay_message_localised(client):
    assert "Loading…" in client.get("/").text
    assert "Зареждане…" in client.get("/bg/jobs").text
