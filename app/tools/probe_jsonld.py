"""Activate the generic JSON-LD adapter for eligible companies:

    python -m app.tools.probe_jsonld

Walks registry companies that HAVE a careers page but NO detected ATS, runs the generic
adapter with a tiny budget, and marks the ones that yield at least one JobPosting as
ats='jsonld' (board id = the careers URL). SPA/no-structured-data sites stay untouched.
"""
import time

from sqlalchemy import select

from ..data.company_repo import upsert_company
from ..data.db import SessionLocal, init_db
from ..data.models import Company
from ..data.sources import jsonld_careers


def run(delay: float = 1.0) -> dict:
    found = empty = 0
    with SessionLocal() as db:
        targets = db.execute(select(Company).where(
            Company.careers_url != "", Company.ats == "")).scalars().all()
        print(f"probing {len(targets)} companies for JobPosting JSON-LD...")
        for c in targets:
            posts = jsonld_careers.fetch(c.careers_url, company_name=c.name,
                                         max_jobs=3, delay=0.3)
            if posts:
                upsert_company(db, c.name, ats="jsonld", ats_slug=c.careers_url)
                print(f"  ✓ {c.name}: {len(posts)}+ postings via {c.careers_url}")
                found += 1
            else:
                empty += 1
            time.sleep(delay)
    return {"activated": found, "no_jsonld": empty}


if __name__ == "__main__":
    init_db()
    print(run())
