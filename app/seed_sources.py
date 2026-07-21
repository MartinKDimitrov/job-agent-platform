from sqlalchemy import select

from .models import Source

# Built-in global sources (user_id = NULL). kind drives which adapter is used later.
BUILTIN = [
    ("Greenhouse (ATS)", "ats_api", "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"),
    ("Lever (ATS)", "ats_api", "https://api.lever.co/v0/postings/{company}"),
    ("Ashby (ATS)", "ats_api", "https://api.ashbyhq.com/posting-api/job-board/{company}"),
    ("Workable (ATS)", "ats_api", "https://apply.workable.com/api/v1/widget/accounts/{company}"),
    ("RemoteOK", "rss", "https://remoteok.com/api"),
    ("We Work Remotely", "rss", "https://weworkremotely.com/remote-jobs.rss"),
    ("LinkedIn", "browser", "https://www.linkedin.com/jobs/search/"),
    ("dev.bg", "browser", "https://dev.bg/company/jobs/"),
    ("jobs.bg", "browser", "https://www.jobs.bg/"),
]


def seed_builtin_sources(db):
    existing = {n for (n,) in db.execute(
        select(Source.name).where(Source.user_id.is_(None))).all()}
    added = 0
    for name, kind, url in BUILTIN:
        if name not in existing:
            db.add(Source(user_id=None, name=name, kind=kind, url=url, enabled=True))
            added += 1
    if added:
        db.commit()
    return added
