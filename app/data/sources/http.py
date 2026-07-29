"""Shared HTTP helper for ATS/RSS adapters: one timeout-bounded GET with safe JSON parsing.

Network failures must never crash the pipeline — a flaky source should degrade to "no postings
this run", not take everything down. So fetch_json returns None on any error and logs it.

429 backoff: when a host rate-limits us (Workable does, per-IP, after detection bursts —
observed live repeatedly), every further request to that host is skipped for a cooldown
(Retry-After honoured when sent) instead of hammering it and extending the penalty window.
Per-process cache — the background ingester and CLI tools each keep their own.
"""
import logging
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

_BACKOFF_DEFAULT = 900.0            # 15 min unless the host says otherwise
# Per-host overrides where 15 min is wrong. Adzuna's 429 is a transient ROLLING-rate throttle
# (a gentle request succeeds seconds later — measured 2026-07-29), so a 15-min stall there turns
# one trip into a dead bulk drain; 60s lets the paced drain recover. Workable's is a real per-IP
# detection ban and keeps the long default.
_BACKOFF_BY_HOST = {"api.adzuna.com": 60.0}
_backoff_until: dict[str, float] = {}   # host -> monotonic deadline


def _host(url: str) -> str:
    return urlparse(url).netloc


def _blocked(url: str) -> bool:
    host = _host(url)
    deadline = _backoff_until.get(host)
    if deadline is None:
        return False
    if time.monotonic() >= deadline:
        del _backoff_until[host]
        return False
    log.info("skipping %s — %s in 429 backoff for %.0fs more",
             url, host, deadline - time.monotonic())
    return True


def _note_429(url: str, response: httpx.Response) -> None:
    host = _host(url)
    try:
        cooldown = float(response.headers.get("Retry-After", ""))
    except ValueError:
        cooldown = _BACKOFF_BY_HOST.get(host, _BACKOFF_DEFAULT)
    _backoff_until[host] = time.monotonic() + max(cooldown, 60.0)
    log.warning("%s rate-limited us (429) — backing off %s for %.0fs",
                _host(url), _host(url), max(cooldown, 60.0))


def _handle_http_error(url: str, e: Exception) -> None:
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
        _note_429(url, e.response)

DEFAULT_TIMEOUT = 15.0
_UA = "JobAgent/0.1 (+https://localhost)"
# Some boards (e.g. dev.bg) time out plain bot UAs but serve their public RSS/pages fine to a
# realistic browser signature. We identify as a browser for public content; robots.txt is
# checked per adapter before a source is added at all.
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml,*/*",
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}


def fetch_json(url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT,
               browser: bool = False, headers: dict | None = None):
    """GET `url` and return parsed JSON, or None on any network/HTTP/parse error. Set
    browser=True for hosts that reject plain bot UAs (RemoteOK, Lever, Ashby); `headers`
    merges on top (API keys — e.g. Arbeitsagentur's public X-API-Key)."""
    if _blocked(url):
        return None
    base_headers = _BROWSER_HEADERS if browser else {"User-Agent": _UA}
    headers = {**base_headers, **(headers or {})}
    try:
        r = httpx.get(url, params=params, timeout=timeout, headers=headers, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError, UnicodeError) as e:
        _handle_http_error(url, e)
        log.warning("fetch_json failed for %s: %s", url, e)
        return None


def post_json(url: str, body: dict, timeout: float = DEFAULT_TIMEOUT):
    """POST JSON and return parsed JSON, or None on any error (same degrade-to-empty contract
    as fetch_json). Needed for Workable's v3 job-search endpoint, which is POST-only."""
    if _blocked(url):
        return None
    try:
        r = httpx.post(url, json=body, timeout=timeout,
                       headers={**_BROWSER_HEADERS, "Content-Type": "application/json"},
                       follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError, UnicodeError) as e:
        _handle_http_error(url, e)
        log.warning("post_json failed for %s: %s", url, e)
        return None


def url_status(url: str, timeout: float = DEFAULT_TIMEOUT) -> int | None:
    """Final HTTP status of `url` (redirects followed), or None when unreachable / in
    backoff. Used by the takedown probe — only an explicit status may retire a posting."""
    if _blocked(url):
        return None
    try:
        r = httpx.get(url, timeout=timeout, headers=_BROWSER_HEADERS, follow_redirects=True)
        if r.status_code == 429:
            _note_429(url, r)
            return None
        return r.status_code
    except httpx.HTTPError as e:
        log.warning("url_status failed for %s: %s", url, e)
        return None


def fetch_text(url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """GET `url` (browser-like headers) and return the body text, or None on any error."""
    if _blocked(url):
        return None
    try:
        r = httpx.get(url, params=params, timeout=timeout,
                      headers=_BROWSER_HEADERS, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except (httpx.HTTPError, UnicodeError) as e:
        _handle_http_error(url, e)
        log.warning("fetch_text failed for %s: %s", url, e)
        return None
