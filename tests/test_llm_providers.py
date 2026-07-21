"""BYOK LLM provider layer (HTTP mocked — hermetic). The key invariants: readable errors,
keys never leak into error text, all providers behind one contract."""
import httpx
import pytest

from app.data.llm import LLMError, get_provider, list_providers
import app.data.llm.gemini as gemini
import app.data.llm.groq as groq
import app.data.llm.ollama as ollama

KEY = "sk-SECRET-123"


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (str(payload) if payload else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# ---- registry ----
def test_registry_has_all_providers():
    names = {p.name for p in list_providers()}
    assert {"gemini", "groq", "ollama"} <= names
    assert get_provider("gemini").needs_key is True
    assert get_provider("ollama").needs_key is False
    assert get_provider("nope") is None


# ---- gemini ----
def test_gemini_success(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": "Hello CV"}]}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(200, payload))
    assert gemini.generate("sys", "prompt", api_key=KEY) == "Hello CV"


def test_gemini_requires_key():
    with pytest.raises(LLMError, match="API key"):
        gemini.generate("sys", "prompt", api_key="")


def test_gemini_bad_key_message(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(403, text="denied"))
    with pytest.raises(LLMError, match="rejected the API key"):
        gemini.generate("s", "p", api_key=KEY)


def test_gemini_error_never_leaks_key(monkeypatch):
    # server echoes the key back in the error body — we must scrub it
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: FakeResp(500, text=f"boom key={KEY}"))
    with pytest.raises(LLMError) as e:
        gemini.generate("s", "p", api_key=KEY)
    assert KEY not in str(e.value)


def test_gemini_network_error_readable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(LLMError, match="request failed"):
        gemini.generate("s", "p", api_key=KEY)


def test_gemini_bad_shape(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(200, {"weird": True}))
    with pytest.raises(LLMError, match="unexpected response"):
        gemini.generate("s", "p", api_key=KEY)


# ---- groq ----
def test_groq_success(monkeypatch):
    payload = {"choices": [{"message": {"content": "Groq says hi"}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(200, payload))
    assert groq.generate("sys", "prompt", api_key=KEY) == "Groq says hi"


def test_groq_requires_key_and_rate_limit(monkeypatch):
    with pytest.raises(LLMError, match="API key"):
        groq.generate("s", "p", api_key="")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(429))
    with pytest.raises(LLMError, match="rate limit"):
        groq.generate("s", "p", api_key=KEY)


# ---- ollama ----
def test_ollama_success_without_key(monkeypatch):
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: FakeResp(200, {"message": {"content": "local hi"}}))
    assert ollama.generate("sys", "prompt") == "local hi"


def test_ollama_not_running_readable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(LLMError, match="is it running"):
        ollama.generate("s", "p")


def test_ollama_missing_model_hint(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(404, text="no model"))
    with pytest.raises(LLMError, match="ollama pull"):
        ollama.generate("s", "p", model="mistral")
