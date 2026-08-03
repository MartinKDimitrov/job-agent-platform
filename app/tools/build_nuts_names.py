"""Generate the NUTS-code -> region-name table for the EURES adapter.

    python -m app.tools.build_nuts_names      # rewrites app/data/sources/nuts_names.py

EURES postings carry their whereabouts as NUTS codes ({"BG": ["BG421"]}); without a name table
the adapter stored bare country codes, and 53.7k of 53.9k EURES rows were "country-only" — the
audit that found this started from a Пловдив ad leaking into a Varna on-site feed. Hand-writing
~1,500 region names for 17 countries is guesswork; Eurostat/GISCO publishes the official list,
so the table is GENERATED (same policy as role_family_i18n: derived data lives in a generated
module, refreshed by rerunning the tool)."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import httpx

_CSV = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/csv/NUTS_AT_2024.csv"
_OUT = Path(__file__).resolve().parents[1] / "data" / "sources" / "nuts_names.py"


def main() -> None:
    r = httpx.get(_CSV, timeout=60)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    # Level 3 (province) and level 2 (region, the fallback when a posting carries only NUTS-2).
    named = {x["NUTS_ID"]: x["NAME_LATN"].strip() for x in rows
             if len(x.get("NUTS_ID", "")) in (4, 5) and x.get("NAME_LATN", "").strip()}
    body = "\n".join(f'    "{k}": "{v}",' for k, v in sorted(named.items()))
    _OUT.write_text(
        '"""NUTS code -> Latin region name — GENERATED from Eurostat/GISCO, do not edit.\n\n'
        "    python -m app.tools.build_nuts_names\n"
        '"""\n\nNUTS_NAMES: dict[str, str] = {\n' + body + "\n}\n",
        encoding="utf-8")
    print(f"wrote {_OUT} — {len(named)} regions (NUTS-2 + NUTS-3)")


if __name__ == "__main__":
    main()
