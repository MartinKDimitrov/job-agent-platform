"""Company-registry persistence: upserts from the detection tool, board lists for ingest."""
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Company

_DETECT_RECHECK_DAYS = 30      # re-probe a company that has no supported ATS at most monthly


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


def _pending_detection_filter(recheck_days: int):
    """Companies that still need ATS detection: no supported ATS yet, have a website to probe,
    and never probed (or not for `recheck_days`). Guessed boards (ats set, inactive) are already
    detected and excluded."""
    cutoff = datetime.utcnow() - timedelta(days=recheck_days)
    return [Company.ats == "", Company.website != "",
            or_(Company.detected_at.is_(None), Company.detected_at < cutoff)]


def detection_countries(db: Session, recheck_days: int = _DETECT_RECHECK_DAYS) -> list[str]:
    """Countries that have companies still needing detection — the shard units for the crawl."""
    rows = db.execute(select(Company.country).where(*_pending_detection_filter(recheck_days))
                      .group_by(Company.country)).scalars()
    return sorted(c for c in rows if c)


def pending_detection_companies(db: Session, country: str | None = None,
                                recheck_days: int = _DETECT_RECHECK_DAYS) -> list[dict]:
    """Candidate entries ({name, country, industry, website}) still needing detection, optionally
    for one country — fed to the detection conveyor (find_careers_url + detect_verified)."""
    q = select(Company).where(*_pending_detection_filter(recheck_days))
    if country:
        q = q.where(Company.country == country)
    return [{"name": c.name, "country": c.country, "industry": c.industry or "",
             "website": c.website} for c in db.execute(q).scalars()]
