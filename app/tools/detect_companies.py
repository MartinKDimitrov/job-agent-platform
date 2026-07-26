"""Registry filler: run ATS detection over company candidates and upsert the results.

    python -m app.tools.detect_companies                 # the built-in BG seed list
    python -m app.tools.detect_companies --eu            # the EU wave (companies_eu.py)
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

from ..data.ats_detect import detect, detect_verified, find_careers_url
from ..data.company_repo import upsert_company
from ..data.companies_bg import BG_COMPANY_NAMES
from ..data.companies_eu import EU_COMPANIES
from ..data.companies_largecap import LARGECAP_COMPANIES
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


def run_entries(entries: list[dict], delay: float = 1.0, force: bool = False) -> dict:
    """EU-wave detection over rich candidate entries ({name, country, industry, website}).
    Differences from run(): the careers page is DISCOVERED from the website first (it is the
    authoritative ATS pointer), and slug guesses go through detect_verified — a guessed
    board must report a matching organization name (the phantom-board rule, automated)."""
    found = missed = skipped = 0
    with SessionLocal() as db:
        for e in entries:
            name = e["name"]
            existing = db.execute(
                select(Company).where(Company.name == name)).scalar_one_or_none()
            if existing and (existing.ats or (not force and (
                    existing.detected_at
                    and datetime.utcnow() - existing.detected_at < _RECHECK_AFTER))):
                skipped += 1
                continue
            try:
                careers = find_careers_url(e.get("website", ""), country=e.get("country"))
                res = detect_verified(name, careers_url=careers)
            except Exception as ex:  # noqa: BLE001 — one bad website must not abort the batch
                print(f"  · {name}: detect error ({str(ex)[:50]})", flush=True)
                db.rollback()
                missed += 1
                time.sleep(delay)
                continue
            if res:
                ats, slug, via = res
                # via='guess' = a name-matching board found by slug guessing — three live
                # rounds of same-name strangers (Alta/Joya/Karma/NATIONAL...) made these
                # HUMAN-REVIEW-ONLY: stored but inactive until the review confirms identity
                upsert_company(db, name, country=e.get("country", "EU"),
                               industry=e.get("industry", ""),
                               website=e.get("website", ""), careers_url=careers,
                               ats=ats, ats_slug=slug, active=(via == "careers"))
                mark = "✓" if via == "careers" else "؟"
                print(f"  {mark} {name} [{e.get('country')}]: {ats}/{slug}"
                      f"{'' if via == 'careers' else '  (guess — pending review)'}",
                      flush=True)
                found += 1
            else:
                c = upsert_company(db, name, country=e.get("country", "EU"),
                                   industry=e.get("industry", ""),
                                   website=e.get("website", ""), careers_url=careers,
                                   active=False)
                c.detected_at = datetime.utcnow()   # remember the miss for _RECHECK_AFTER
                db.commit()
                print(f"  · {name} [{e.get('country')}]: no verified ATS", flush=True)
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
    if "--largecap" in sys.argv:
        entries = LARGECAP_COMPANIES
        if "--country" in sys.argv:
            entries = [e for e in entries if e["country"] == country]
        print(f"probing {len(entries)} large-cap companies (force={force})...")
        print(run_entries(entries, force=force))
    elif "--eu" in sys.argv:
        print(f"probing {len(EU_COMPANIES)} EU companies (force={force})...")
        print(run_entries(EU_COMPANIES, force=force))
    else:
        names = args or BG_COMPANY_NAMES
        print(f"probing {len(names)} companies ({country}, force={force})...")
        print(run(names, country=country, force=force))
