"""Import a company CSV (Derrick / BuiltWith / any name+website export) AND run the verified
ATS detection conveyor over it in one pass — the intake used to measure a paid source's
real ATS hit-rate.

    python -m app.tools.detect_csv <file.csv> [--country XX] [--limit N] [--offset N] [--force]

Unlike import_csv (which only parks rows inactive for later), this discovers each company's
careers page and runs detect_verified immediately, so the printed found/missed tally IS the
hit-rate for that CSV. Rows on a supported ATS are stored active; misses stay inactive as the
honest "checked" record. Column names are auto-detected (see import_csv). Long CSVs: run in
the background — one careers fetch + ATS probes per company at ~1s spacing.
"""
from __future__ import annotations

import csv
import sys

from .detect_companies import run_entries
from .import_csv import _domain_to_url, _pick, _NAME_COLS, _SITE_COLS, _COUNTRY_COLS
from ..data.db import init_db

_INDUSTRY_COLS = ("industry", "sector", "vertical", "category", "bransche")

# Derrick spells the country out ("Germany"); the registry keys on ISO-2 ("DE"). Map the
# ones we actually target; anything unknown is passed through uppercased as-is.
_ISO = {
    "germany": "DE", "france": "FR", "italy": "IT", "spain": "ES", "united kingdom": "GB",
    "great britain": "GB", "uk": "GB", "switzerland": "CH", "austria": "AT",
    "netherlands": "NL", "belgium": "BE", "poland": "PL", "sweden": "SE", "denmark": "DK",
    "norway": "NO", "finland": "FI", "ireland": "IE", "portugal": "PT", "czechia": "CZ",
    "czech republic": "CZ", "estonia": "EE", "latvia": "LV", "lithuania": "LT",
    "bulgaria": "BG", "romania": "RO", "greece": "GR", "hungary": "HU", "luxembourg": "LU",
}


def _iso(country: str) -> str:
    c = (country or "").strip()
    return _ISO.get(c.lower(), c.upper())


def _load_entries(path: str, default_country: str, limit: int, offset: int) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        ni = _pick(header, _NAME_COLS)
        si = _pick(header, _SITE_COLS)
        ci = _pick(header, _COUNTRY_COLS)
        ii = _pick(header, _INDUSTRY_COLS)
        if ni is None:
            raise SystemExit(f"no name column found in header: {header}")
        entries: list[dict] = []
        for idx, row in enumerate(reader):
            if idx < offset:
                continue
            if len(entries) >= limit or ni >= len(row):
                break
            name = (row[ni] or "").strip()[:255]
            website = _domain_to_url(row[si]) if si is not None and si < len(row) else ""
            if not name or not website:
                continue  # no site => nothing to discover a careers page from
            raw_country = (row[ci].strip() if ci is not None and ci < len(row) and row[ci]
                           else default_country) or "EU"
            industry = (row[ii].strip() if ii is not None and ii < len(row) else "")
            entries.append({"name": name, "country": _iso(raw_country),
                            "industry": industry, "website": website})
    return entries


if __name__ == "__main__":
    init_db()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: python -m app.tools.detect_csv <file.csv> [--country XX]")
    country = sys.argv[sys.argv.index("--country") + 1] if "--country" in sys.argv else ""
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10_000_000
    offset = int(sys.argv[sys.argv.index("--offset") + 1]) if "--offset" in sys.argv else 0
    force = "--force" in sys.argv
    entries = _load_entries(args[0], country, limit, offset)
    print(f"detecting {len(entries)} companies from {args[0]} (force={force})...", flush=True)
    print(run_entries(entries, force=force))
