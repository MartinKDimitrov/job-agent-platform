"""Daily digest job (orchestrator, agent A10).

Runs once a day (system cron on the VPS: `python -m app.jobs`). For every ACTIVE user with at
least one profile, it searches the fetched postings and emails a digest of the NEW matches above
their threshold — never re-notifying a match already sent. Fully generic: no assumption about
profession or seniority; each user's own profile drives their filters and score.

Gating (see activity.py): skip users who marked "I found a job" or who haven't been seen in the
last 5 days — no point spending crawl/scoring on them.
"""
from datetime import datetime
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.models import User, Profile, Match, Posting, DigestEntry
from ...data.sources import jobtiger
from ...data.sources.seed_boards import GREENHOUSE_BOARDS
from .search import fetch_all, fetch_extra, ingest_from_sources, search_db
from ...data.activity_repo import get_activity
from ...domain.activity_rules import is_active_for_search
from ...data.mailer import send_email
from ..run_stats import RunStats
from ...data.metrics_repo import record_run


# Email copy lives here (not presentation.i18n) so the application layer stays free of
# presentation imports. The user's language comes from UserActivity (set by the EN/BG
# switcher) — the cron job has no request cookie to read.
_EMAIL_COPY = {
    "en": {"hi": "Hi", "intro": "{n} new job match(es) for your profiles:",
           "match": "match", "profile": "profile", "apply": "Apply",
           "footer": ("You get this because your searches are active. "
                      "Mark “I found a job” in your account to pause."),
           "subject": "{n} new job match(es) for you"},
    "bg": {"hi": "Здравей", "intro": "{n} нови съвпадения за профилите ти:",
           "match": "съвпадение", "profile": "профил", "apply": "Кандидатствай",
           "footer": ("Получаваш този имейл, защото търсенето ти е активно. "
                      "Отбележи „Намерих работа“ в акаунта си, за да го спреш."),
           "subject": "{n} нови съвпадения с работа за теб"},
}


def _compose(user: User, items, lang: str = "en") -> tuple[str, str]:
    """items: list of (profile, match, posting). Returns (subject, html) in `lang`."""
    c = _EMAIL_COPY.get(lang, _EMAIL_COPY["en"])
    lis = []
    for p, m, post in items:
        apply_url = post.apply_url or post.url or "#"
        lis.append(
            f"<li><b>{escape(post.title)}</b> — {escape(post.company)} "
            f"({int(m.score)}% {c['match']} · {escape(post.location or 'n/a')}) "
            f"· {c['profile']} <i>{escape(p.name)}</i> — "
            f"<a href='{escape(apply_url)}'>{c['apply']}</a></li>")
    hi = f" {escape(user.name)}" if user.name else ""
    html = (f"<p>{c['hi']}{hi},</p>"
            f"<p>{c['intro'].format(n=len(items))}</p>"
            f"<ul>{''.join(lis)}</ul>"
            f"<p style='color:#777;font-size:12px'>{c['footer']}</p>")
    return c["subject"].format(n=len(items)), html


def run_daily_digest(db: Session, boards=None, send=send_email, now=None,
                     jobtiger_limit: int = 0, jobtiger_delay: float = jobtiger.CRAWL_DELAY) -> dict:
    """`jobtiger_limit` > 0 additionally crawls up to that many NEW JobTiger pages (30s apart,
    per their robots crawl-delay) — background/cron only; 0 keeps runs fast and network-free
    beyond the fast sources."""
    boards = GREENHOUSE_BOARDS if boards is None else boards
    now = now or datetime.utcnow()
    started = datetime.utcnow()
    stats = RunStats()
    try:
        raw = fetch_all(boards, stats=stats) + fetch_extra(stats=stats)   # once for the whole run
        if jobtiger_limit > 0:
            known = {u for (u,) in db.execute(select(Posting.url)).all() if u}
            jt = jobtiger.fetch(limit=jobtiger_limit, delay=jobtiger_delay, skip_urls=known)
            raw += jt
            stats.source("jobtiger", fetched=len(jt))
        users = db.execute(select(User)).scalars().all()

        # gate users first, so the single ingest below runs targeted queries only for them
        active: list[tuple[User, list[Profile], object]] = []
        skipped = 0
        for u in users:
            profiles = db.execute(select(Profile).where(Profile.user_id == u.id)).scalars().all()
            if not profiles:
                continue
            act = get_activity(db, u.id)
            if not is_active_for_search(u, act, now):
                skipped += 1
                continue
            active.append((u, profiles, act))

        # ONE ingest for the whole run (DB-first search: writes here, reads below)
        ingest_from_sources(db, boards=boards, raw_postings=raw,
                            profiles=[p for _, ps, _ in active for p in ps], stats=stats)

        notified = emails_sent = new_matches = 0
        for u, profiles, act in active:
            user_lang = (act.lang if act and act.lang else "en")

            already = set(db.execute(
                select(DigestEntry.profile_id, DigestEntry.posting_id)
                .where(DigestEntry.user_id == u.id)).all())
            fresh = []
            for p in profiles:
                search_db(db, p, stats=stats)
                q = (select(Match, Posting).join(Posting, Match.posting_id == Posting.id)
                     .where(Match.profile_id == p.id, Match.score >= p.min_match)
                     .order_by(Match.score.desc()))
                for m, post in db.execute(q).all():
                    if (p.id, post.id) in already:
                        continue
                    already.add((p.id, post.id))
                    fresh.append((p, m, post))

            if fresh:
                subject, html = _compose(u, fresh, user_lang)
                if send(u.email, subject, html):
                    emails_sent += 1
                for p, m, post in fresh:
                    db.add(DigestEntry(user_id=u.id, profile_id=p.id, posting_id=post.id))
                notified += 1
                new_matches += len(fresh)
        db.commit()
        stats.add(users=len(users), notified=notified, emails_sent=emails_sent,
                  new_matches=new_matches, skipped=skipped)
        record_run(db, "daily", stats, started, ok=True)
        return {"users": len(users), "notified": notified, "emails_sent": emails_sent,
                "new_matches": new_matches, "skipped": skipped}
    except Exception as e:  # noqa: BLE001 — record the failure, then re-raise
        record_run(db, "daily", stats, started, ok=False, error=str(e))
        raise

