from sqlalchemy import func, select

from .models import Posting, Source

# Built-in global sources (user_id = NULL). kind drives which adapter is used later.
# The /sources page shows this as "where we search" — list ONLY platforms an adapter actually
# crawls (owner rule: no aspirational entries; LinkedIn and jobs.bg were removed as such).
# Workable is back since 16в: the v3 endpoint adapter works (the old v1 widget was dead).
BUILTIN = [
    ("Greenhouse (ATS)", "ats_api", "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"),
    ("Lever (ATS)", "ats_api", "https://api.lever.co/v0/postings/{company}"),
    ("Ashby (ATS)", "ats_api", "https://api.ashbyhq.com/posting-api/job-board/{company}"),
    ("Workable (ATS)", "ats_api", "https://apply.workable.com/api/v3/accounts/{company}/jobs"),
    ("Teamtailor (ATS)", "ats_api", "https://{careers-site}/jobs.rss"),
    ("RemoteOK", "rss", "https://remoteok.com/api"),
    ("We Work Remotely", "rss", "https://weworkremotely.com/remote-jobs.rss"),
    ("dev.bg", "rss", "https://dev.bg/company/jobs/"),
    ("JobTiger", "sitemap", "https://www.jobtiger.bg/"),
]

# Formerly-seeded rows that no adapter serves — removed everywhere so the sources page
# never claims coverage we don't have.
RETIRED = {"LinkedIn", "jobs.bg"}


def seed_builtin_sources(db):
    existing = {n for (n,) in db.execute(
        select(Source.name).where(Source.user_id.is_(None))).all()}
    changed = 0
    for name, kind, url in BUILTIN:
        if name not in existing:
            db.add(Source(user_id=None, name=name, kind=kind, url=url, enabled=True))
            changed += 1
    for s in db.execute(select(Source).where(
            Source.user_id.is_(None), Source.name.in_(RETIRED))).scalars():
        refs = db.execute(select(func.count(Posting.id))
                          .where(Posting.source_id == s.id)).scalar()
        if refs:                      # a posting points here — disable instead of breaking FK
            s.enabled = False
        else:
            db.delete(s)
        changed += 1
    if changed:
        db.commit()
    return changed
