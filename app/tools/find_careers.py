"""Careers-page discovery over the multi-industry seed list (owner request, 2026-07-22):

    python -m app.tools.find_careers

For every seed company: upsert (name/industry/website), find its careers page starting
from the website (homepage link first, common paths as fallback), store `careers_url`,
then run ATS detection against that page (this is how custom-domain boards like
careers.mypos.com are found). Polite: ~1s between companies.
"""
import time

from sqlalchemy import select

from ..data.ats_detect import detect, find_careers_url
from ..data.companies_bg import BG_COMPANIES
from ..data.company_repo import upsert_company
from ..data.db import SessionLocal, init_db
from ..data.models import Company


def run(companies: list[dict] | None = None, delay: float = 1.0) -> dict:
    companies = BG_COMPANIES if companies is None else companies
    careers_found = ats_found = 0
    with SessionLocal() as db:
        for spec in companies:
            name = spec["name"]
            c = upsert_company(db, name, industry=spec.get("industry", ""),
                               website=spec.get("website", ""))
            if not c.careers_url and c.website:
                url = find_careers_url(c.website)
                if url:
                    upsert_company(db, name, careers_url=url)
                    careers_found += 1
                    print(f"  ✓ careers  {name}: {url}")
            db.refresh(c)
            if not c.ats and c.careers_url:
                res = detect(name, careers_url=c.careers_url)
                if res:
                    ats, slug = res
                    upsert_company(db, name, ats=ats, ats_slug=slug)
                    ats_found += 1
                    print(f"  ★ ats      {name}: {ats}/{slug}")
            time.sleep(delay)
        total = len(db.execute(select(Company)).scalars().all())
    return {"companies": total, "careers_found_now": careers_found, "ats_found_now": ats_found}


if __name__ == "__main__":
    init_db()
    print(f"discovering careers pages for {len(BG_COMPANIES)} companies...")
    print(run())
