"""Shared HTTP helper for ATS/RSS adapters: one timeout-bounded GET with safe JSON parsing.

Network failures must never crash the pipeline — a flaky source should degrade to "no postings
this run", not take everything down. So fetch_json returns None on any error and logs it.
"""
import logging

import httpx

log = logging.getLogger(__name__)

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


def fetch_json(url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT):
    """GET `url` and return parsed JSON, or None on any network/HTTP/parse error."""
    try:
        r = httpx.get(url, params=params, timeout=timeout,
                      headers={"User-Agent": _UA}, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("fetch_json failed for %s: %s", url, e)
        return None


def fetch_text(url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """GET `url` (browser-like headers) and return the body text, or None on any error."""
    try:
        r = httpx.get(url, params=params, timeout=timeout,
                      headers=_BROWSER_HEADERS, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except httpx.HTTPError as e:
        log.warning("fetch_text failed for %s: %s", url, e)
        return None
