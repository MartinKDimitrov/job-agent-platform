"""Company-registry persistence: upserts from the detection tool, board lists for ingest."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Company


def upsert_company(db: Session, name: str, *, country: str = "BG", careers_url: str = "",
                   industry: str = "", website: str = "",
                   ats: str = "", ats_slug: str = "", active: bool | None = None) -> Company:
    c = db.execute(select(Company).where(Company.name == name)).scalar_one_or_none()
    if c is None:
        c = Company(name=name)
        db.add(c)
    c.country = country or c.country
    c.industry = industry or c.industry
    c.website = website or c.website
    c.careers_url = careers_url or c.careers_url
    if ats:
        c.ats, c.ats_slug, c.detected_at = ats, ats_slug, datetime.utcnow()
    if active is None:
        c.active = bool(c.ats)          # crawlable companies default to active
    else:
        c.active = active
    db.commit()
    db.refresh(c)
    return c


def boards_for(db: Session, ats: str, country: str | None = None) -> list[tuple[str, str]]:
    """(slug, display name) pairs the ingest should crawl for one ATS. `country` (ISO-2) limits
    to one country's boards — the unit the sharded/windowed ingest schedules independently."""
    q = select(Company).where(
        Company.ats == ats, Company.active.is_(True), Company.ats_slug != "")
    if country:
        q = q.where(Company.country == country)
    return [(c.ats_slug, c.name) for c in db.execute(q).scalars()]


def board_countries(db: Session) -> list[str]:
    """ISO-2 codes that have at least one active board — the countries the window shards over."""
    rows = db.execute(select(Company.country).where(
        Company.ats != "", Company.active.is_(True), Company.ats_slug != "")
        .group_by(Company.country)).scalars()
    return sorted(c for c in rows if c)
