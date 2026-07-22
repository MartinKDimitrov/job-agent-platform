"""Registry filler: run ATS detection over company candidates and upsert the results.

    python -m app.tools.detect_companies                 # the built-in BG seed list
    python -m app.tools.detect_companies "Име" [...]     # specific companies
    python -m app.tools.detect_companies --country EU "Име" [...]

Polite by design: a few public JSON GETs per company, ~1s apart. Companies without a
supported ATS are stored inactive (ats='') so re-runs skip re-probing recent misses and we
keep an honest record of what was checked.
"""
import sys
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from ..data.ats_detect import detect
from ..data.company_repo import upsert_company
from ..data.companies_bg import BG_COMPANY_NAMES
from ..data.db import SessionLocal
from ..data.models import Company

_RECHECK_AFTER = timedelta(days=30)   # re-probe known misses monthly, not on every run


def run(names: list[str], country: str = "BG", delay: float = 1.0, force: bool = False) -> dict:
    """`force=True` re-probes recorded misses too — needed right after a NEW ATS adapter
    lands (companies skipped as 'no supported ATS' may live on the new platform)."""
    found = missed = skipped = 0
    with SessionLocal() as db:
        for name in names:
            existing = db.execute(
                select(Company).where(Company.name == name)).scalar_one_or_none()
            if existing and (existing.ats or (not force and (
                    existing.detected_at
                    and datetime.utcnow() - existing.detected_at < _RECHECK_AFTER))):
                skipped += 1
                continue
            res = detect(name)
            if res:
                ats, slug = res
                upsert_company(db, name, country=country, ats=ats, ats_slug=slug)
                print(f"  ✓ {name}: {ats}/{slug}")
                found += 1
            else:
                c = upsert_company(db, name, country=country, active=False)
                c.detected_at = datetime.utcnow()   # remember the miss for _RECHECK_AFTER
                db.commit()
                missed += 1
            time.sleep(delay)
    return {"found": found, "missed": missed, "skipped": skipped}


if __name__ == "__main__":
    from ..data.db import init_db
    init_db()          # standalone CLI — make sure new tables exist before we write
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    country = "BG"
    if "--country" in sys.argv:
        country = sys.argv[sys.argv.index("--country") + 1]
        args = [a for a in args if a != country]
    force = "--force" in sys.argv
    names = args or BG_COMPANY_NAMES
    print(f"probing {len(names)} companies ({country}, force={force})...")
    print(run(names, country=country, force=force))
