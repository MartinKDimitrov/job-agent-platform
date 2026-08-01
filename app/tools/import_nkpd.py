"""Attach official Bulgarian NKPD-2011 positions + qualification levels to ESCO occupations.

ESCO stays the multilingual backbone (professions + skills, all UI languages). This overlays the
BG market with the National Classification of Professions and Positions: the MLSP publishes an
NKPD-2011<->ESCO correspondence table (Excel), which we join to our occupations by their Bulgarian
ESCO label. Each occupation gets `nkpd = [{code, title, level, rel}]` where level is the 5th digit
of the 8-digit NKPD code (minimum education/qualification level). BG onboarding shows these.

    python -m app.tools.import_nkpd            # download the table from MLSP and populate
    python -m app.tools.import_nkpd <path.xlsx>  # use a local copy
"""
import io
import sys

import httpx
import openpyxl
from sqlalchemy import select, text

from ..data.db import SessionLocal, engine
from ..data.models import Occupation

NKPD_ESCO_XLSX = "https://www.mlsp.government.bg/uploads/24/nkpd/tablitsa-nkpd-esco.xlsx"


def _load_map(src) -> dict:
    """ESCO Bulgarian label (lowercased) -> list of NKPD positions, in table order."""
    ws = openpyxl.load_workbook(src, read_only=True)["Export"]
    by_esco: dict[str, list] = {}
    for code, nkpd, esco, rel in (r[:4] for r in ws.iter_rows(min_row=3, values_only=True)):
        if not esco or not nkpd:
            continue
        raw = str(code).replace(" ", "")
        by_esco.setdefault(str(esco).strip().lower(), []).append({
            "code": str(code).strip(),
            "title": str(nkpd).strip(),
            "level": raw[4] if len(raw) >= 5 else "",   # 5th digit = min qualification level
            "rel": str(rel or "").split(" ")[0],         # Точно / Тясно / Близко / Широко
        })
    return by_esco


def _ensure_column() -> None:
    """create_all() won't add a column to an already-existing table — add it if missing."""
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE occupations ADD COLUMN IF NOT EXISTS nkpd JSON"))
    except Exception:  # noqa: BLE001 — SQLite/other dialects already have it via create_all
        pass


def run(session_factory=SessionLocal, xlsx_path: str | None = None) -> dict:
    _ensure_column()
    src = xlsx_path or io.BytesIO(httpx.get(NKPD_ESCO_XLSX, timeout=90).content)
    by_esco = _load_map(src)
    updated = positions = 0
    with session_factory() as db:
        for o in db.execute(select(Occupation)).scalars():
            m = by_esco.get(((o.labels or {}).get("bg", "")).strip().lower())
            if not m:
                continue
            seen, items = set(), []
            for x in m:
                if x["title"] not in seen:
                    seen.add(x["title"])
                    items.append(x)
            o.nkpd = items
            updated += 1
            positions += len(items)
        db.commit()
    return {"distinct_esco_labels": len(by_esco), "occupations_updated": updated,
            "nkpd_positions_attached": positions}


if __name__ == "__main__":
    print(run(xlsx_path=sys.argv[1] if len(sys.argv) > 1 else None))
