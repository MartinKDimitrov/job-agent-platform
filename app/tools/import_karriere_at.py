"""Austrian employer import from karriere.at's own sitemaps (robots.txt: `User-agent: *`
fully allowed; the Disallow:/ lines apply to BLEXBot/AhrefsBot only — verified 2026-07-24).

    python -m app.tools.import_karriere_at --limit 2000 [--min-jobs 1] [--offset 0]

The company sitemap lists ~28.8k firms — the whole Austrian market. Each /f/<slug> profile
page carries the display name, the current job count ("54 offene Jobs") and, crucially, the
company's OWN careers/website link — which is exactly what our identity-verified ATS
detection wants (the careers page is the authoritative path). We import companies with
active jobs as AT candidates; detection runs separately over the registered careers URLs.

Polite by design: one paced GET per profile; slices via --offset/--limit make the full
sweep a rolling job, not one marathon.
"""
from __future__ import annotations

import re
import sys
import time
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from ..data.company_repo import upsert_company
from ..data.db import SessionLocal, init_db
from ..data.sources.http import fetch_text

SITEMAP = "https://www.karriere.at/static/sitemaps/sitemap-firmen-https.xml"

# karriere.at's own network/partner boards — never a company's own site
_NETWORK_HOSTS = ("karriere.at", "kcdn.at", "jobs.at", "itstellen.at", "financejobs.at",
                  "salescareer.at", "hokify.at", "jobradius.at", "norika.com",
                  "google.", "facebook.", "linkedin.", "youtube.", "instagram.",
                  "xing.", "twitter.", "x.com", "apple.", "tiktok.")

_JOBS_RE = re.compile(r"(\d+)\s+offene[rn]?\s+Jobs?", re.I)
_TITLE_RE = re.compile(r"<title>([^<|]+?)(?:\s*[-|]\s*[^<]*)?</title>", re.I)
# some profile titles use ':' instead of '- City |' ("X GmbH: Karrierechancen, Kontaktdaten,
# Fotos ...") — strip that marketing tail from the captured name
_TITLE_TAIL_RE = re.compile(r"\s*:\s*Karrierechancen.*$", re.I)
_HREF_RE = re.compile(r'href="(https?://[^"]+)"', re.I)
_CAREERS_HINT = re.compile(r"karriere|career|jobs|stellen", re.I)


def company_slugs() -> list[str]:
    """All company slugs from the sitemap, in sitemap order."""
    xml = fetch_text(SITEMAP)
    if not xml:
        return []
    root = ET.fromstring(xml)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    out = []
    for loc in root.findall(".//sm:loc", ns):
        path = urlparse((loc.text or "").strip()).path
        if path.startswith("/f/"):
            out.append(unquote(path[3:]))
    return out


def parse_profile(html: str) -> dict | None:
    """{name, jobs, careers_url, website} from a /f/<slug> profile page."""
    if not html:
        return None
    m = _TITLE_RE.search(html)
    if not m:
        return None
    name = _TITLE_TAIL_RE.sub("", m.group(1)).strip()
    jobs = 0
    jm = _JOBS_RE.search(html)
    if jm:
        jobs = int(jm.group(1))
    careers_url = website = ""
    for href in _HREF_RE.findall(html):
        host = urlparse(href).netloc.lower()
        if not host or any(n in host for n in _NETWORK_HOSTS):
            continue
        if re.search(r"\.(css|js|png|jpe?g|svg|woff2?|ico|pdf)(\?|$)", href, re.I):
            continue
        if _CAREERS_HINT.search(urlparse(href).path) and not careers_url:
            careers_url = href
        elif not website:
            website = f"https://{host}"
    if careers_url and not website:
        website = f"https://{urlparse(careers_url).netloc}"
    return {"name": name, "jobs": jobs, "careers_url": careers_url, "website": website}


def run(limit: int = 2000, offset: int = 0, min_jobs: int = 1, delay: float = 0.8) -> dict:
    slugs = company_slugs()
    print(f"sitemap: {len(slugs)} companies; processing [{offset}:{offset + limit}]",
          flush=True)
    imported = skipped = failed = 0
    with SessionLocal() as db:
        for slug in slugs[offset:offset + limit]:
            html = fetch_text(f"https://www.karriere.at/f/{slug}")
            info = parse_profile(html or "")
            if not info:
                failed += 1
                time.sleep(delay)
                continue
            if info["jobs"] < min_jobs or not (info["careers_url"] or info["website"]):
                skipped += 1
                time.sleep(delay)
                continue
            upsert_company(db, info["name"][:255], country="AT",
                           website=info["website"], careers_url=info["careers_url"],
                           active=False)      # candidate; detection activates on a verified hit
            imported += 1
            if imported % 50 == 0:
                print(f"  … {imported} imported (last: {info['name']}, "
                      f"{info['jobs']} jobs)", flush=True)
            time.sleep(delay)
    return {"imported": imported, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    init_db()
    def _arg(flag, default):
        return int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default
    print(run(limit=_arg("--limit", 2000), offset=_arg("--offset", 0),
              min_jobs=_arg("--min-jobs", 1)))
