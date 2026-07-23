"""429 backoff cache in the shared HTTP layer: one rate-limit answer silences the whole
host for the cooldown, so detection bursts can't extend the penalty window."""
import time

import httpx
import pytest

import app.data.sources.http as h


@pytest.fixture(autouse=True)
def clean_backoff():
    h._backoff_until.clear()
    yield
    h._backoff_until.clear()


def _resp429(url: str, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(429, headers=headers, request=httpx.Request("GET", url))


def test_429_blocks_the_host_for_the_cooldown(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        raise httpx.HTTPStatusError("429", request=httpx.Request("GET", url),
                                    response=_resp429(url))
    monkeypatch.setattr(h.httpx, "get", fake_get)
    assert h.fetch_json("https://apply.workable.com/api/v3/accounts/a/jobs") is None
    assert h.fetch_json("https://apply.workable.com/api/v3/accounts/b/jobs") is None
    assert h.fetch_text("https://apply.workable.com/whatever") is None
    assert len(calls) == 1                       # only the FIRST request reached the host
    # a different host is unaffected
    monkeypatch.setattr(h.httpx, "get", lambda url, **kw: (_ for _ in ()).throw(
        httpx.ConnectError("x")))
    calls.clear()
    h.fetch_json("https://boards-api.greenhouse.io/v1/boards/x/jobs")


def test_retry_after_header_is_honoured(monkeypatch):
    def fake_post(url, **kw):
        raise httpx.HTTPStatusError("429", request=httpx.Request("POST", url),
                                    response=_resp429(url, retry_after="1200"))
    monkeypatch.setattr(h.httpx, "post", fake_post)
    h.post_json("https://apply.workable.com/api/v3/accounts/a/jobs", {})
    deadline = h._backoff_until["apply.workable.com"]
    assert 1100 < deadline - time.monotonic() <= 1200


def test_backoff_expires(monkeypatch):
    h._backoff_until["apply.workable.com"] = time.monotonic() - 1   # already expired
    monkeypatch.setattr(h.httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"ok": True}, request=httpx.Request("GET", url)))
    assert h.fetch_json("https://apply.workable.com/x") == {"ok": True}
    assert "apply.workable.com" not in h._backoff_until


def test_non_429_errors_do_not_trigger_backoff(monkeypatch):
    def fake_get(url, **kw):
        raise httpx.HTTPStatusError("404", request=httpx.Request("GET", url),
                                    response=httpx.Response(404, request=httpx.Request("GET", url)))
    monkeypatch.setattr(h.httpx, "get", fake_get)
    h.fetch_json("https://boards-api.greenhouse.io/v1/boards/x/jobs")
    assert h._backoff_until == {}
