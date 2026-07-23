"""On-demand search: fetch from source adapters, score against a profile, persist matches.

This is the first end-to-end wiring of the product promise — "skills in → matches out" — for one
source type (Greenhouse). The daily scheduler (Step 16) will run the same `run_search` in the
background over a managed source list; here it is triggered synchronously by the user's
"Search now" button. Order matters for cost: cheap relevance pre-filter first, then a capped set
goes through requirement extraction + embeddings, so a 500-job board doesn't blow up the run.
"""
from __future__ import annotations

import logging
import re

import time
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import settings

from ...data.models import Posting, Match
from ...data.sources import (greenhouse, dev_bg, remoteok, wwr, lever, ashby, workable,
                             teamtailor, jsonld_careers, smartrecruiters, recruitee, personio)
from ...domain.entities import RawPosting
from ...data.ingest import ingest
from ...data.sources.seed_boards import GREENHOUSE_BOARDS, LEVER_COMPANIES, ASHBY_COMPANIES
from ...domain.extraction import extract_requirements
from ...domain.scoring import embed, score
from ...domain.filters import passes_hard_filters

log = logging.getLogger(__name__)


def _lever_all() -> list[RawPosting]:
    return [rp for slug, name in LEVER_COMPANIES for rp in lever.fetch(slug, name)]


def _ashby_all() -> list[RawPosting]:
    return [rp for slug, name in ASHBY_COMPANIES for rp in ashby.fetch(slug, name)]


# (name, callable) so per-source metrics are unambiguous — the adapters are all module-level
# `fetch`, so we can't rely on __name__. Fast sources run on every "Search now" (kept snappy):
# remoteok/wwr are one HTTP request each and remote-only boards — exactly what a remote-pref
# profile needs live (owner report: 'everything comes from dev.bg'). Lever/Ashby iterate a
# company list (dozens of requests), so they stay in the daily background job.
FAST_SOURCES = [("dev_bg", dev_bg.fetch), ("remoteok", remoteok.fetch), ("wwr", wwr.fetch)]
EXTRA_SOURCES = [("lever", _lever_all), ("ashby", _ashby_all)]


def _profile_search_terms(profile) -> list[str]:
    """Search phrases for targeted source queries, from the profile's target roles — e.g.
    'Android Developer, Team Lead' -> ['android developer', 'team lead']. Phrases (not single
    tokens) keep the search precise; capped to keep request counts polite."""
    terms = []
    for part in (profile.target_roles or "").split(","):
        t = part.strip().lower()
        if len(t) >= 4:
            terms.append(t)
    return terms[:3]


def _dev_bg_targeted(profile) -> list[RawPosting]:
    """dev.bg's global feed only covers ~6 recent days; its search feed reaches everything.
    Query it with the profile's own target roles so a Business Analyst gets BA postings and an
    Android dev gets the Android ones (this was the 'always the same offers' bug)."""
    terms = _profile_search_terms(profile)
    if not terms:
        return []
    return dev_bg.fetch(search_terms=terms, pages=0)   # pages=0: skip the global feed here

# Profile-aware targeted sources, run per Search-now (and per profile in the daily digest).
PROFILE_SOURCES = [("dev_bg_targeted", _dev_bg_targeted)]


def _safe(name: str, fn, stats=None) -> list[RawPosting]:
    """Run a source, isolating its failure — one broken source must not kill the whole run.
    Records the fetch count (or error) into `stats` when given (see app/metrics.RunStats)."""
    try:
        res = list(fn())
        if stats is not None:
            stats.source(name, fetched=len(res))
        return res
    except Exception as e:  # noqa: BLE001 — any adapter error degrades to "no postings"
        log.warning("source %s failed: %s", name, e)
        if stats is not None:
            stats.source(name, error=str(e)[:200])
        return []

DEFAULT_LIMIT = 40
_TOKEN_RE = re.compile(r"[a-z0-9\+\#\.]+")

# Tool tokens too generic to signal title relevance — the "Git" skill was matching GitLab's
# "Tenant Scale: Git" job title and similar accidents (api/rest/sdk appear in countless titles).
_GENERIC_TOKENS = {"git", "api", "rest", "sdk", "app", "apps", "web", "code"}


def _profile_keywords(profile) -> set[str]:
    text = f"{profile.target_roles or ''} {profile.skills or ''}".lower()
    return {tok for tok in _TOKEN_RE.findall(text)
            if len(tok) > 2 and tok not in _GENERIC_TOKENS}


def _relevant(rp: RawPosting, keywords: set[str]) -> bool:
    """Cheap pre-filter: keep a posting only if its TITLE shares a whole token with the profile
    keywords (exact token match, not substring — 'api' must not match 'capital'). Avoids
    embedding hundreds of obviously-irrelevant roles (e.g. Sales jobs for an Android profile)."""
    if not keywords:
        return True
    title_tokens = set(_TOKEN_RE.findall((rp.title or "").lower()))
    return bool(keywords & title_tokens)


def fetch_all(boards=None, stats=None) -> list[RawPosting]:
    """Fetch the fast sources once (Greenhouse boards + dev.bg + RemoteOK + WWR) — used by both
    "Search now" and the daily job. Each source is error-isolated. Company-list ATS crawls
    (Lever/Ashby via fetch_extra) and crawl-delayed sources (JobTiger) are daily-job only."""
    boards = GREENHOUSE_BOARDS if boards is None else boards
    out: list[RawPosting] = []
    gh_count = 0
    for token, name in boards:
        try:
            posts = greenhouse.fetch(token, company_name=name)
            out.extend(posts)
            gh_count += len(posts)
        except Exception as e:  # noqa: BLE001
            log.warning("greenhouse %s failed: %s", token, e)
            if stats is not None:
                stats.source("greenhouse", error=str(e)[:200])
    if stats is not None:
        stats.source("greenhouse", fetched=gh_count)
    for name, src in FAST_SOURCES:
        out.extend(_safe(name, src, stats))
    return out


def fetch_extra(stats=None) -> list[RawPosting]:
    """RemoteOK / WWR / Lever / Ashby — broader coverage for the daily background run."""
    out: list[RawPosting] = []
    for name, src in EXTRA_SOURCES:
        out.extend(_safe(name, src, stats))
    return out


def _embed_list(text: str):
    """embed() as a JSON-storable list (numpy array otherwise), or None without a model."""
    v = embed(text)
    return None if v is None else [float(x) for x in v]


def _enrich_new_postings(db: Session) -> int:
    """Ingest-time enrichment: extract requirements and compute the E5 vector ONCE per posting,
    stored on the row — searches then read instead of re-computing (DB-first search).
    Without an embedding model (tests) requirements still get extracted; embed() fails fast."""
    enriched = 0
    q = select(Posting).where(or_(Posting.embedding.is_(None), Posting.requirements.is_(None)))
    for post in db.execute(q).scalars():
        if post.requirements is None:
            post.requirements = extract_requirements(post.description or "")
        if post.embedding is None:
            post.embedding = _embed_list(post.description or post.title)
            if post.embedding is not None:
                enriched += 1
    db.commit()
    return enriched


def _registry_postings(db: Session, stats=None) -> list[RawPosting]:
    """Career pages from the company REGISTRY (ROADMAP 16б): every active company with a
    detected ATS board, fetched through the matching adapter. One adapter serves them all."""
    from ...data.company_repo import boards_for
    adapters = {"greenhouse": greenhouse.fetch, "lever": lever.fetch, "ashby": ashby.fetch,
                "workable": workable.fetch, "teamtailor": teamtailor.fetch,
                "jsonld": jsonld_careers.fetch, "smartrecruiters": smartrecruiters.fetch,
                "recruitee": recruitee.fetch, "personio": personio.fetch}
    out: list[RawPosting] = []
    for ats, fetch_fn in adapters.items():
        count = 0
        for slug, name in boards_for(db, ats):
            try:
                posts = fetch_fn(slug, company_name=name)
            except Exception as e:  # noqa: BLE001 — one dead board must not kill the run
                log.warning("registry %s/%s failed: %s", ats, slug, e)
                continue
            out.extend(posts)
            count += len(posts)
        if stats is not None and count:
            stats.source(f"registry_{ats}", fetched=count)
    return out


def ingest_from_sources(db: Session, boards=None, raw_postings=None, profiles=(),
                        stats=None) -> dict:
    """The WRITE side of DB-first search: fetch everything, persist (dedup), enrich.
    Runs on a schedule (every INGEST_EVERY_HOURS) and inside the daily digest — never on the
    user's Search-now path. `profiles` adds profile-targeted queries (dev.bg search feed) so
    each user's target roles reach postings the global recency window misses."""
    boards = GREENHOUSE_BOARDS if boards is None else boards
    if raw_postings is None:
        raw_postings = fetch_all(boards, stats=stats)
    raw_postings = list(raw_postings) + _registry_postings(db, stats=stats)
    seen_urls = {rp.url for rp in raw_postings if rp.url}
    for profile in profiles:
        for name, src in PROFILE_SOURCES:
            try:
                targeted = [rp for rp in src(profile) if rp.url not in seen_urls]
            except Exception as e:  # noqa: BLE001 — a broken source must not kill the run
                log.warning("targeted source %s failed: %s", name, e)
                if stats is not None:
                    stats.source(name, error=str(e)[:200])
                continue
            if stats is not None:
                stats.source(name, fetched=len(targeted))
            raw_postings.extend(targeted)
            seen_urls.update(rp.url for rp in targeted if rp.url)
    ing = ingest(db, raw_postings)
    enriched = _enrich_new_postings(db)
    retired = retire_stale_postings(db)
    unseen = retire_unseen_board_postings(db)
    taken_down = probe_taken_down_urls(db)
    if stats is not None:
        stats.add(added=ing["added"], deduped=ing["deduped"], enriched=enriched,
                  retired=retired, unseen_retired=unseen, taken_down=taken_down)
    return {"fetched": len(raw_postings), "added": ing["added"], "enriched": enriched,
            "retired": retired, "unseen_retired": unseen, "taken_down": taken_down}


# Sources that show only a RECENT WINDOW — a posting dropping out of their feed proves
# nothing about being taken down (the board sources, by contrast, list everything current).
_WINDOW_HOSTS = ("dev.bg", "jobtiger.bg", "remoteok.com", "weworkremotely.com")
_UNSEEN_RETIRE_HOURS = 48        # ~8 ingest cycles of grace against transient fetch failures
_PROBE_BUDGET = 30               # URL takedown checks per ingest cycle
_PROBE_HOSTS = ("dev.bg", "remoteok.com", "weworkremotely.com")   # NOT jobtiger (Crawl-Delay 30)


def _is_window_url(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in _WINDOW_HOSTS)


def retire_unseen_board_postings(db: Session, hours: int = _UNSEEN_RETIRE_HOURS) -> int:
    """Takedown detection for FULL-LIST boards: registry companies' boards return their whole
    current list every cycle, so a posting of theirs that no fetch has shown for `hours` is
    gone from the source — retire it. Window-source URLs (dev.bg...) are exempt (their feeds
    only show recent items), as are rows without last_seen_at (not yet backfilled)."""
    from ...data.models import Company
    board_companies = {name for (name,) in db.execute(
        select(Company.name).where(Company.ats != "", Company.active.is_(True)))}
    if not board_companies:
        return 0
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    retired = 0
    rows = db.execute(select(Posting).where(
        Posting.is_live.is_(True), Posting.company.in_(board_companies),
        Posting.last_seen_at.isnot(None), Posting.last_seen_at < cutoff)).scalars()
    for post in rows:
        if _is_window_url(post.url):
            continue
        post.is_live = False
        retired += 1
    db.commit()
    return retired


def probe_taken_down_urls(db: Session, budget: int | None = None,
                          delay: float = 0.5, sleep=time.sleep) -> int:
    """Takedown detection for WINDOW sources: politely GET the least-recently-checked live
    postings' URLs; an explicit 404/410 retires the posting. Network errors / backoff leave
    it untouched (only proof retires). JobTiger is excluded (its 30s crawl delay)."""
    from ...data.sources.http import url_status
    budget = settings.takedown_probe_budget if budget is None else budget
    if not budget:
        return 0
    candidates = db.execute(select(Posting).where(Posting.is_live.is_(True))
                            .order_by(func.coalesce(Posting.last_checked_at,
                                                    Posting.first_seen))).scalars()
    checked = retired = 0
    now = datetime.utcnow()
    for post in candidates:
        if checked >= budget:
            break
        if not _is_window_url(post.url) or "jobtiger" in (post.url or ""):
            continue
        if checked:
            sleep(delay)
        status = url_status(post.url)
        checked += 1
        post.last_checked_at = now
        if status in (404, 410):
            post.is_live = False
            retired += 1
    db.commit()
    return retired


def retire_stale_postings(db: Session, max_age_days: int | None = None) -> int:
    """Owner rule: postings older than a month disappear from every surface. Age is the
    SOURCE's publish date when the adapter provided one, else our first_seen. Runs on each
    ingest cycle; retired rows keep their data (is_live=False) but no query shows them."""
    days = settings.posting_max_age_days if max_age_days is None else max_age_days
    if not days:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=days)
    res = db.execute(update(Posting)
                     .where(Posting.is_live.is_(True),
                            func.coalesce(Posting.posted_at, Posting.first_seen) < cutoff)
                     .values(is_live=False))
    db.commit()
    return res.rowcount or 0


def search_db(db: Session, profile, limit: int | None = None, stats=None) -> dict:
    """The READ side: score the profile against the postings ALREADY in our index — no network,
    so Search now answers in well under a second. Vectors come precomputed from the rows.

    Query shape matters: the title pre-filter runs over (id, title) pairs only, and full rows
    (description + vector JSON) load just for the relevant few — pulling all columns of the
    whole index measured ~2.5s over the staging tunnel vs ~0.2s this way."""
    keywords = _profile_keywords(profile)
    ptext = profile.as_text()
    if profile.embedding is None:            # cached on the row; cleared on profile edit
        profile.embedding = _embed_list(ptext)
    id_titles = db.execute(select(Posting.id, Posting.title)
                           .where(Posting.is_live.is_(True))).all()
    pool = len(id_titles)
    relevant_ids = [pid for pid, title in id_titles
                    if not keywords
                    or keywords & set(_TOKEN_RE.findall((title or "").lower()))]
    existing_by_post = {m.posting_id: m for m in db.execute(
        select(Match).where(Match.profile_id == profile.id)).scalars()}
    scored = filtered = matched = 0
    posts = db.execute(select(Posting).where(Posting.id.in_(relevant_ids))
                       .order_by(Posting.first_seen.desc())).scalars() if relevant_ids else []
    for post in posts:
        # A match the user can't act on is noise: postings without ANY link never create NEW
        # matches (junk/manually-scaffolded rows). Existing matches (the owner pasted the JD
        # via the manual form) still refresh their score.
        if not (post.apply_url or post.url) and post.id not in existing_by_post:
            continue
        ok, _reason = passes_hard_filters(profile, post.title, post.location, post.description)
        if not ok:
            filtered += 1
            continue
        if post.requirements is None:
            post.requirements = extract_requirements(post.description or "")
        sc, covered, missing = score(ptext, post.description or post.title, post.requirements,
                                     profile_vec=profile.embedding, posting_vec=post.embedding)
        existing = existing_by_post.get(post.id)
        if existing:
            existing.score, existing.covered, existing.missing = sc, covered, missing
        else:
            db.add(Match(profile_id=profile.id, posting_id=post.id,
                         score=sc, covered=covered, missing=missing))
        scored += 1
        if sc >= profile.min_match:
            matched += 1
        if limit is not None and scored >= limit:
            break
    try:
        db.commit()
    except IntegrityError:
        # two overlapping searches for the same profile (double-click) can both pass the
        # existing-Match check and collide on uq_profile_posting — the other run already saved
        # equivalent matches, so losing this commit is harmless. Roll back so the session stays
        # usable for the caller (record_run etc.).
        db.rollback()
        log.info("concurrent search for profile %s — matches saved by the other run", profile.id)
    if stats is not None:
        stats.add(filtered=filtered, scored=scored, matched=matched)
    return {"pool": pool, "filtered": filtered, "scored": scored, "matched": matched}


def run_search(db: Session, profile, boards=None, limit: int | None = None,
               raw_postings=None, stats=None) -> dict:
    """Ingest + score in one call (compatibility path — the daily digest and tests use it).
    The Search-now route calls `search_db` directly and never fetches."""
    ing = ingest_from_sources(db, boards=boards, raw_postings=raw_postings,
                              profiles=[profile], stats=stats)
    res = search_db(db, profile, limit=limit, stats=stats)
    return {"fetched": ing["fetched"], "added": ing["added"], **res}
