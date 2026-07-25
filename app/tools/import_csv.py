"""Import companies from a CSV export (BuiltWith, Derrick, or any name/website/country list)
into the registry as detection candidates.

    python -m app.tools.import_csv <file.csv> [--country XX] [--limit N]

The paid data sources (BuiltWith "companies using Workday", Derrick country/sector discovery)
all export CSV — this is the intake for that. Column names are auto-detected from a header
(case-insensitive): company/name/organization for the name; website/domain/url/site for the
site; country/countrycode/geo for the country (falls back to --country). Rows are stored
inactive (active=False) — the detection conveyor (find_careers_url + ATS incl. Workday/
SuccessFactors) activates the ones on a supported ATS. Deduped against the registry.
"""
from __future__ import annotations

import csv
import re
import sys

from ..data.company_repo import upsert_company
from ..data.db import SessionLocal, init_db

_NAME_COLS = ("company", "name", "company name", "organization", "organisation", "account",
              "firma", "cég", "société", "azienda", "empresa")
_SITE_COLS = ("website", "domain", "url", "site", "web", "homepage", "company website")
_COUNTRY_COLS = ("country", "countrycode", "country code", "geo", "location", "hq country")

# Derrick exports annotate every header with a source tag, e.g. "name (SCBP)",
# "website (SCBP)". Strip a trailing "(...)" so the column still matches.
_TAG_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _norm_header(h: str) -> str:
    return _TAG_RE.sub("", h.strip().lower())


def _pick(header: list[str], candidates: tuple[str, ...]) -> int | None:
    low = [_norm_header(h) for h in header]
    for c in candidates:
        if c in low:
            return low.index(c)
    return None


def _domain_to_url(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if not v.startswith(("http://", "https://")):
        v = "https://" + v.lstrip("/")
    return v


def run(path: str, default_country: str = "", limit: int = 10_000_000) -> dict:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        ni = _pick(header, _NAME_COLS)
        si = _pick(header, _SITE_COLS)
        ci = _pick(header, _COUNTRY_COLS)
        if ni is None:
            raise SystemExit(f"no name column found in header: {header}")
        imported = skipped = 0
        with SessionLocal() as db:
            for row in reader:
                if imported + skipped >= limit or ni >= len(row):
                    break
                name = (row[ni] or "").strip()[:255]
                website = _domain_to_url(row[si]) if si is not None and si < len(row) else ""
                country = (row[ci].strip()[:8] if ci is not None and ci < len(row) and row[ci]
                           else default_country) or "EU"
                if not name or not website:
                    skipped += 1
                    continue
                upsert_company(db, name, country=country.upper(), website=website, active=False)
                imported += 1
                if imported % 500 == 0:
                    print(f"  … {imported} imported", flush=True)
    return {"imported": imported, "skipped": skipped}


if __name__ == "__main__":
    init_db()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: python -m app.tools.import_csv <file.csv> [--country XX]")
    country = ""
    if "--country" in sys.argv:
        country = sys.argv[sys.argv.index("--country") + 1]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10_000_000
    print(run(args[0], default_country=country, limit=limit))
