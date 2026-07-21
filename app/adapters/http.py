"""Shared HTTP helper for ATS/RSS adapters: one timeout-bounded GET with safe JSON parsing.

Network failures must never crash the pipeline — a flaky source should degrade to "no postings
this run", not take everything down. So fetch_json returns None on any error and logs it.
"""
import logging

import httpx

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
_UA = "JobAgent/0.1 (+https://localhost)"


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
