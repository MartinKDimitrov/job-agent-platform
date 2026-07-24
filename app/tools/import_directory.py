"""Generalized national company-directory harvester (the proven karriere.at model, config-
driven for reuse across countries).

The national job boards are used ONLY as a COMPANY CATALOGUE — we harvest company names +
their OWN websites, then read jobs from each company's own careers page/ATS via the detection
conveyor. Never as a job source (owner principle).

    python -m app.tools.import_directory hu [--limit 2000] [--offset 0]

Each site config: a company SITEMAP of profile URLs (the rare, harvestable pattern — most
national boards render their directory as a SPA and yield nothing statically; audited
2026-07-24). We fetch the sitemap, take the profile URLs, and from each profile page extract
the company's own website (social/network hosts excluded). Companies are stored as candidates;
detection (incl. Workday) activates the ones on a supported ATS. Paced + sliced for rolling runs.
"""
from __future__ import annotations

import re
import sys
import time
from urllib.parse import urlparse

from ..data.company_repo import upsert_company
from ..data.db import SessionLocal, init_db
from ..data.sources.http import fetch_text

# hosts that are never a company's OWN site (the board, socials, trackers)
_NETWORK = ("facebook.", "linkedin.", "youtube.", "instagram.", "twitter.", "x.com",
            "google.", "apple.", "tiktok.", "xing.", "wikipedia.", "goo.gl", "bit.ly")

SITES: dict[str, dict] = {
    # Hungary — profession.hu publishes a company sitemap of /cegek/{slug} profiles (~2900);
    # each profile page links the company's own website. Verified live 2026-07-24.
    "hu": {
        "name": "profession.hu",
        "country": "HU",
        "sitemap": "https://www.profession.hu/sitemap-directory-listings.xml",
        "profile_re": re.compile(r"https://www\.profession\.hu/cegek/[a-z0-9-]+"),
        "name_from_slug": lambda url: url.rstrip("/").rsplit("/", 1)[-1]
                          .replace("-", " ").title(),
    },
}

_HREF_RE = re.compile(r'href="(https?://[^"]+)"', re.I)
_ASSET_RE = re.compile(r"\.(css|js|png|jpe?g|svg|woff2?|ico|pdf)(\?|$)", re.I)


def _company_website(profile_html: str, board_host: str) -> str:
    """The first external, non-network, non-asset link on a company profile page."""
    for href in _HREF_RE.findall(profile_html or ""):
        host = urlparse(href).netloc.lower()
        if not host or board_host in host or any(n in host for n in _NETWORK):
            continue
        if _ASSET_RE.search(href):
            continue
        return f"https://{host}"
    return ""


def profile_urls(cfg: dict) -> list[str]:
    xml = fetch_text(cfg["sitemap"]) or ""
    return list(dict.fromkeys(cfg["profile_re"].findall(xml)))


def run(site: str, limit: int = 2000, offset: int = 0, delay: float = 0.7) -> dict:
    cfg = SITES[site]
    board_host = urlparse(cfg["sitemap"]).netloc.replace("www.", "")
    urls = profile_urls(cfg)
    print(f"{cfg['name']}: {len(urls)} company profiles; processing [{offset}:{offset+limit}]",
          flush=True)
    imported = skipped = 0
    with SessionLocal() as db:
        for url in urls[offset:offset + limit]:
            html = fetch_text(url)
            website = _company_website(html or "", board_host)
            if not website:
                skipped += 1
                time.sleep(delay)
                continue
            name = cfg["name_from_slug"](url)[:255]
            upsert_company(db, name, country=cfg["country"], website=website, active=False)
            imported += 1
            if imported % 50 == 0:
                print(f"  … {imported} imported (last: {name})", flush=True)
            time.sleep(delay)
    return {"imported": imported, "skipped": skipped}


if __name__ == "__main__":
    init_db()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    site = args[0] if args else "hu"

    def _arg(flag, d):
        return int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else d
    print(run(site, limit=_arg("--limit", 2000), offset=_arg("--offset", 0)))
