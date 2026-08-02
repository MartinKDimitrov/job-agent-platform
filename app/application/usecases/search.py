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
                             teamtailor, jsonld_careers, smartrecruiters, recruitee, personio,
                             karriere_nrw, arbeitnow, eures)
from ...domain.entities import RawPosting
from ...data.ingest import ingest
from ...data.sources.seed_boards import GREENHOUSE_BOARDS, LEVER_COMPANIES, ASHBY_COMPANIES
from ...domain.extraction import extract_requirements
from ...domain.scoring import (EMBED_VERSION, embed_passage, embed_query, freshness_factor,
                               posting_embed_text, score)


def posting_age_days(post, now=None) -> float | None:
    """Age from the SOURCE's publish date, else our first sighting."""
    basis = post.posted_at or post.first_seen
    if basis is None:
        return None
    return max(0.0, ((now or datetime.utcnow()) - basis).total_seconds() / 86400)


def posting_freshness(post, now=None) -> float:
    return freshness_factor(posting_age_days(post, now),
                            settings.freshness_fresh_days,
                            settings.freshness_at_30d, settings.freshness_at_60d)


def soft_factors(profile, post, expectation=None) -> dict:
    """The soft score multipliers, by name — the SINGLE source both scoring and the 'why this
    score' breakdown read, so the explanation can never drift from the number. Each is a cheap
    pure function of profile+posting (no embeddings), so the breakdown is computable at display
    time without a stored column."""
    from ...domain.salary import parse_salary, posting_salary, salary_factor
    if expectation is None:
        expectation = parse_salary(profile.salary_expectation or "")
    return {
        "freshness": posting_freshness(post),
        "salary": salary_factor(posting_salary(post), expectation,
                                low=settings.salary_low_factor, fit=settings.salary_fit_boost),
        "language": language_factor(profile.languages, post.description or post.title,
                                    post.location or "",
                                    unreadable=settings.language_unreadable_factor,
                                    foreign_country=settings.language_foreign_country_factor),
        "seniority": seniority_factor(profile, post.title,
                                      underqualified=settings.seniority_underqualified_factor,
                                      overqualified=settings.seniority_overqualified_factor),
        "role_family": role_family_factor(profile, post.title,
                                          adjacent=settings.role_family_adjacent_factor),
        "location": location_factor(profile, post.title, post.location or "", post.description or "",
                                    elsewhere=settings.location_elsewhere_factor),
        "qualification": qualification_factor(
            profile, f"{post.title or ''}\n{post.description or ''}",
            underqualified=settings.qualification_underqualified_factor,
            need=getattr(post, "education_level", None)),
    }
from ...domain.filters import (passes_hard_filters, seniority_factor, location_factor,
                               qualification_factor)
from ...domain.role_family import role_family_factor
from ...domain.language import language_factor

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
FAST_SOURCES = [("dev_bg", dev_bg.fetch), ("remoteok", remoteok.fetch), ("wwr", wwr.fetch),
                ("karriere_nrw", karriere_nrw.fetch),
                ("arbeitnow", arbeitnow.fetch), ("eures", eures.fetch)]
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


def _dev_bg_targeted(terms: list[str]) -> list[RawPosting]:
    """dev.bg's global feed only covers ~6 recent days; its search feed reaches everything.
    Queried per UNIQUE role term (grouped across all active profiles — 500 users with
    'android developer' cost ONE query per cycle, not 500)."""
    if not terms:
        return []
    return dev_bg.fetch(search_terms=terms, pages=0)   # pages=0: skip the global feed here

def _jobtech_targeted(terms: list[str]) -> list[RawPosting]:
    """Platsbanken (Sweden) via the fully open JobTech JobSearch API — first EU board
    adapter. Targeted like dev.bg: one API search per unique role term per cycle (a full
    dump is ~100k live postings)."""
    if not terms:
        return []
    from ...data.sources import jobtech
    return jobtech.fetch(search_terms=terms)


def _arbeitsagentur_targeted(terms: list[str]) -> list[RawPosting]:
    """Bundesagentur für Arbeit (Germany) via the public Jobsuche API — second EU board
    adapter. Same targeted discipline; detail GETs are paced inside the adapter."""
    if not terms:
        return []
    from ...data.sources import arbeitsagentur
    return arbeitsagentur.fetch(search_terms=terms)


def _adzuna_targeted(terms: list[str]) -> list[RawPosting]:
    """Adzuna multi-country aggregator via the free API — one call per unique role term
    x country per run. Silent no-op until ADZUNA_APP_ID/KEY land in .env."""
    if not terms:
        return []
    from ...data.sources import adzuna
    return adzuna.fetch(search_terms=terms)


def _jooble_targeted(terms: list[str]) -> list[RawPosting]:
    """Jooble pan-European aggregator via the free API — one call per unique role term per run.
    The one aggregator that natively covers BG + the Baltics. No-op until JOOBLE_API_KEY lands."""
    if not terms:
        return []
    from ...data.sources import jooble
    return jooble.fetch(search_terms=terms, max_terms=settings.jooble_max_terms)


def _careerjet_targeted(terms: list[str]) -> list[RawPosting]:
    """Careerjet global aggregator (90+ countries incl. BG) via the free v4 API — one call per
    role term × locale. No-op until CAREERJET_API_KEY lands in .env."""
    if not terms:
        return []
    from ...data.sources import careerjet
    return careerjet.fetch(search_terms=terms)


def _francetravail_targeted(terms: list[str]) -> list[RawPosting]:
    """France Travail via the free OAuth API — third EU board adapter. Silent no-op until
    FRANCETRAVAIL_CLIENT_ID/SECRET land in .env (register at francetravail.io)."""
    if not terms:
        return []
    from ...data.sources import francetravail
    return francetravail.fetch(search_terms=terms)


# Role-term-targeted sources: each receives the DEDUPLICATED term list for the whole run.
PROFILE_SOURCES = [("dev_bg_targeted", _dev_bg_targeted),
                   ("jobtech_targeted", _jobtech_targeted),
                   ("arbeitsagentur_targeted", _arbeitsagentur_targeted),
                   ("francetravail_targeted", _francetravail_targeted),
                   ("adzuna_targeted", _adzuna_targeted),
                   ("jooble_targeted", _jooble_targeted),
                   ("careerjet_targeted", _careerjet_targeted)]


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
_GENERIC_TOKENS = {"git", "api", "rest", "sdk", "app", "apps", "web", "code",
                   # role-suffix / seniority words: they appear across thousands of unrelated
                   # titles, so on their own they aren't recall signal (an 'engineer' token alone
                   # matched ~14k titles). The distinctive tokens (python, machine, welder…) stay.
                   "engineer", "engineering", "developer", "dev", "manager", "management",
                   "specialist", "analyst", "consultant", "lead", "senior", "junior", "intern",
                   "associate", "officer", "coordinator", "administrator", "assistant",
                   "director", "head", "principal", "staff", "professional"}


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


def _as_list(v):
    """Vector as a JSON-storable list (numpy array otherwise), or None without a model."""
    return None if v is None else [float(x) for x in v]


def _enrich_new_postings(db: Session) -> int:
    """Ingest-time enrichment: extract requirements and compute the E5 vector ONCE per posting,
    stored on the row — searches then read instead of re-computing (DB-first search).
    Vectors are version-stamped (EMBED_VERSION): changing the input construction or prefix
    mode lazily re-embeds affected rows here. Without a model (tests) requirements still
    get extracted; embed fails fast."""
    enriched = 0
    q = select(Posting).where(or_(Posting.embedding.is_(None),
                                  Posting.embedding_version != EMBED_VERSION,
                                  Posting.requirements.is_(None)))
    from ...domain.filters import extract_qualification_level
    for post in db.execute(q).scalars():
        if post.requirements is None:
            post.requirements = extract_requirements(post.description or "")
        if post.education_level is None:      # collected once, like the parsed salary
            post.education_level = extract_qualification_level(
                f"{post.title or ''}\n{post.description or ''}")
        if post.embedding is None or post.embedding_version != EMBED_VERSION:
            vec = _as_list(embed_passage(posting_embed_text(post.title, post.requirements)))
            if vec is not None:
                post.embedding, post.embedding_version = vec, EMBED_VERSION
                enriched += 1
    db.commit()
    return enriched


_registry_adapters_cache: dict | None = None


def _registry_adapters() -> dict:
    """ats -> adapter fetch fn. Built once (Workday/SF/rexx/softgarden imported lazily to keep
    module load order simple); one adapter serves all boards on its platform."""
    global _registry_adapters_cache
    if _registry_adapters_cache is None:
        from ...data.sources import workday, successfactors, rexx, softgarden, dvinci
        _registry_adapters_cache = {
            "greenhouse": greenhouse.fetch, "lever": lever.fetch, "ashby": ashby.fetch,
            "workable": workable.fetch, "teamtailor": teamtailor.fetch,
            "jsonld": jsonld_careers.fetch, "smartrecruiters": smartrecruiters.fetch,
            "recruitee": recruitee.fetch, "personio": personio.fetch,
            "workday": workday.fetch, "successfactors": successfactors.fetch,
            "rexx": rexx.fetch, "softgarden": softgarden.fetch, "dvinci": dvinci.fetch}
    return _registry_adapters_cache


def registry_boards(db: Session, country: str | None = None) -> list[tuple[str, str, str]]:
    """(ats, slug, name) for every active registry board (optionally one country) — the unit the
    windowed ingest shards and batches over."""
    from ...data.company_repo import boards_for
    out: list[tuple[str, str, str]] = []
    for ats in _registry_adapters():
        out.extend((ats, slug, name) for slug, name in boards_for(db, ats, country=country))
    return out


def fetch_registry_boards(boards: list[tuple[str, str, str]], stats=None) -> list[RawPosting]:
    """Fetch an explicit (ats, slug, name) board list through the matching adapters, error-
    isolated per board (one dead board never aborts a shard)."""
    adapters = _registry_adapters()
    out: list[RawPosting] = []
    counts: dict[str, int] = {}
    for ats, slug, name in boards:
        fetch_fn = adapters.get(ats)
        if fetch_fn is None:
            continue
        try:
            posts = fetch_fn(slug, company_name=name)
        except Exception as e:  # noqa: BLE001 — one dead board must not kill the run
            log.warning("registry %s/%s failed: %s", ats, slug, e)
            continue
        out.extend(posts)
        counts[ats] = counts.get(ats, 0) + len(posts)
    if stats is not None:
        for ats, n in counts.items():
            if n:
                stats.source(f"registry_{ats}", fetched=n)
    return out


def _registry_postings(db: Session, stats=None, country: str | None = None) -> list[RawPosting]:
    """All registry career pages (optionally one country), fetched via the matching adapter."""
    return fetch_registry_boards(registry_boards(db, country=country), stats=stats)


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
    # role terms grouped across ALL profiles: one targeted query per unique term per run
    terms = sorted({t for profile in profiles for t in _profile_search_terms(profile)})
    if terms:
        for name, src in PROFILE_SOURCES:
            try:
                targeted = [rp for rp in src(terms) if rp.url not in seen_urls]
            except Exception as e:  # noqa: BLE001 — a broken source must not kill the run
                log.warning("targeted source %s failed: %s", name, e)
                if stats is not None:
                    stats.source(name, error=str(e)[:200])
                continue
            if stats is not None:
                stats.source(name, fetched=len(targeted))
            raw_postings.extend(targeted)
            seen_urls.update(rp.url for rp in targeted if rp.url)
    persisted = persist_postings(db, raw_postings, stats=stats)
    maint = run_ingest_maintenance(db, stats=stats)
    return {"fetched": persisted["fetched"], "added": persisted["added"], **maint}


def persist_postings(db: Session, raw_postings, stats=None) -> dict:
    """Persist + dedup a batch of fetched raw postings (the WRITE of one shard). No global
    maintenance — that runs once per window in run_ingest_maintenance."""
    ing = ingest(db, list(raw_postings))
    if stats is not None:
        stats.add(added=ing["added"], deduped=ing["deduped"])
    return {"fetched": len(raw_postings), "added": ing["added"], "deduped": ing["deduped"]}


def run_ingest_maintenance(db: Session, stats=None) -> dict:
    """Global post-fetch upkeep — runs ONCE per window, after every shard has written: enrich
    new postings (requirements + E5 vector), annotate, retire stale/unseen/taken-down, merge
    near-duplicates, refresh the vector cache. Idempotent and shard-independent."""
    enriched = _enrich_new_postings(db)
    from .annotate import annotate_postings
    ann = annotate_postings(db)
    retired = retire_stale_postings(db)
    near_dups = merge_near_duplicates(db)
    unseen = retire_unseen_board_postings(db)
    taken_down = probe_taken_down_urls(db)
    from .. import vector_cache
    vector_cache.invalidate()             # the index changed — recall reloads lazily
    if stats is not None:
        stats.add(enriched=enriched, annotated=ann["annotated"],
                  unknown_skills=ann.get("unknown_skills", 0), retired=retired,
                  near_dups=near_dups, unseen_retired=unseen, taken_down=taken_down)
    return {"enriched": enriched, "annotated": ann["annotated"], "retired": retired,
            "near_dups": near_dups, "unseen_retired": unseen, "taken_down": taken_down}


def run_ingest_shard_boards(db: Session, boards: list[tuple[str, str, str]], stats=None) -> dict:
    """Fetch + persist one explicit board batch — a single isolated shard of the windowed
    ingest (no global maintenance)."""
    return persist_postings(db, fetch_registry_boards(boards, stats=stats), stats=stats)


def run_ingest_global(db: Session, profiles=(), stats=None) -> dict:
    """The fixed (non-registry) sources as one 'global' shard: seed boards + fast/remote feeds
    (fetch_all) and per-profile targeted queries. Registry boards are handled by country shards."""
    raw = fetch_all(GREENHOUSE_BOARDS, stats=stats)
    seen = {rp.url for rp in raw if rp.url}
    terms = sorted({t for profile in profiles for t in _profile_search_terms(profile)})
    if terms:
        for name, src in PROFILE_SOURCES:
            try:
                targeted = [rp for rp in src(terms) if rp.url not in seen]
            except Exception as e:  # noqa: BLE001 — a broken source must not kill the run
                log.warning("targeted source %s failed: %s", name, e)
                if stats is not None:
                    stats.source(name, error=str(e)[:200])
                continue
            if stats is not None:
                stats.source(name, fetched=len(targeted))
            raw.extend(targeted)
            seen.update(rp.url for rp in targeted if rp.url)
    return persist_postings(db, raw, stats=stats)


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


# Aggregators (Adzuna/Jooble/Careerjet) return the expired ad as a 200 page ("This listing went
# offline", "The job position is no longer available") instead of a 404 — so a status check misses
# them. Detect the expiry from the page content too.
_EXPIRED_RE = re.compile(
    r"no longer available|listing went offline|this (?:job|position|vacancy|listing) (?:has )?"
    r"(?:expired|is expired|is closed|has closed|has been filled|is no longer)|"
    r"job (?:position|posting|advert) is no longer|position has been filled|vacancy is closed|"
    r"offer (?:has )?expired|обявата (?:е )?(?:изтекла|неактивна|затворена)|позицията е заета", re.I)


def probe_taken_down_urls(db: Session, budget: int | None = None,
                          delay: float = 0.5, sleep=time.sleep) -> int:
    """Takedown detection: politely fetch the least-recently-checked live postings' pages. Retire
    on an explicit 404/410 OR an 'expired / no longer available' page — the latter is how the
    aggregators (Adzuna/Jooble/Careerjet) sign a dead ad while still returning HTTP 200. Network
    errors / backoff leave it untouched (only proof retires). JobTiger is excluded (30s crawl delay)."""
    from ...data.sources.http import url_status, fetch_text
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
        url = post.url
        if not url or "jobtiger" in url:
            continue
        if checked:
            sleep(delay)
        checked += 1
        post.last_checked_at = now
        html = fetch_text(url)                       # follows the aggregator's redirect
        if html is None:                             # couldn't read it -> confirm a hard 404/410
            if url_status(url) in (404, 410):
                post.is_live = False
                retired += 1
        elif _EXPIRED_RE.search(html):               # 200, but the page says the ad is dead
            post.is_live = False
            retired += 1
    db.commit()
    return retired


def merge_near_duplicates(db: Session, cosine_threshold: float | None = None) -> int:
    """Reworded reposts of the SAME job across DIFFERENT boards (the original purpose):
    same normalized company + DIFFERENT url hosts + similar titles + stored-vector cosine
    above the threshold → the less informative row retires.

    Hard-learned gates (first live run false-merged 'Senior AI Engineer' with 'Lead AI
    Engineer' and two unrelated roles posted the same week): clean-text vectors share a
    company's boilerplate, so same-source postings can exceed 0.97 cosine while being
    genuinely different jobs. Same-host pairs are therefore NEVER merged, the close-dates
    alternative is gone, and title similarity is required — all three gates AND-ed."""
    import numpy as np
    from urllib.parse import urlparse
    from ...domain.dedup import normalize_company, similar_titles
    threshold = settings.near_dup_cosine if cosine_threshold is None else cosine_threshold
    if not threshold:
        return 0
    by_co: dict[str, list[Posting]] = {}
    for p in db.execute(select(Posting).where(Posting.is_live.is_(True),
                                              Posting.embedding.isnot(None))).scalars():
        norm = normalize_company(p.company)
        if norm:
            by_co.setdefault(norm, []).append(p)
    merged = 0
    for group in by_co.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda p: (len(p.description or ""), p.first_seen or 0), reverse=True)
        kept: list[Posting] = []
        for p in group:
            dup = None
            p_host = urlparse(p.url or "").netloc
            for k in kept:
                if p_host == urlparse(k.url or "").netloc:
                    continue                    # same source = likely two real openings
                if not similar_titles(p.title, k.title):
                    continue
                cos = float(np.dot(np.asarray(p.embedding), np.asarray(k.embedding)))
                if cos > threshold:
                    dup = k
                    break
            if dup is None:
                kept.append(p)
            else:
                if p.apply_url and p.apply_url != p.url and dup.apply_url == dup.url:
                    dup.apply_url = p.apply_url          # inherit the canonical ATS link
                p.is_live = False
                merged += 1
    db.commit()
    return merged


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


def _title_names_role(title: str, role_names: list[str]) -> bool:
    """Does the posting title name the candidate's occupation, in any language? ESCO labels carry
    both genders ("Schweißer/Schweißerin"), so each side of a slash counts on its own."""
    low = (title or "").lower()
    for name in role_names:
        for part in name.replace("/", " ").split():
            if len(part) >= 4 and part in low:
                return True
    return False


def search_db(db: Session, profile, limit: int | None = None, stats=None, verify: bool = True) -> dict:
    """The READ side: score the profile against the postings ALREADY in our index — no network,
    so Search now answers in well under a second. Vectors come precomputed from the rows.

    Query shape matters: the title pre-filter runs over (id, title) pairs only, and full rows
    (description + vector JSON) load just for the relevant few — pulling all columns of the
    whole index measured ~2.5s over the staging tunnel vs ~0.2s this way."""
    keywords = _profile_keywords(profile)
    ptext = profile.as_text()
    from ...data.taxonomy_repo import role_names_all_languages
    # the occupation's name in every language ESCO has it in — used both for the profile vector
    # and to tell whether a posting's TITLE actually names this occupation
    role_names = [n.lower() for n in role_names_all_languages(db, profile.target_roles or "")
                  if len(n) >= 4]
    from ...domain.skills import parse_skill_years
    skill_years = parse_skill_years(profile.skills) or None   # {skill: years}; once per search
    from ...domain.role_family import families as _role_families
    profile_families = _role_families(profile.target_roles or "")   # once per search
    from ...domain.salary import parse_salary, posting_salary, salary_factor
    expectation = parse_salary(profile.salary_expectation or "")   # once per search
    if profile.embedding is None:            # cached on the row; cleared on profile edit
        # The occupation named in every language it exists in — postings are written in the
        # source language and E5 scores cross-lingual pairs much lower than same-language ones,
        # which is why a Bulgarian tradesperson's own market never ranked (see taxonomy_repo).
        from ...data.taxonomy_repo import role_names_all_languages
        names = role_names_all_languages(db, profile.target_roles or "")
        text = profile.embed_text()
        if names:
            text = " · ".join(names) + " · " + text
        profile.embedding = _as_list(embed_query(text))
    id_titles = db.execute(select(Posting.id, Posting.title, Posting.location)
                           .where(Posting.is_live.is_(True))).all()
    pool = len(id_titles)
    # HYBRID RECALL (Phase 5): titles alone cut recall — 'Backend' never sees 'Platform
    # Engineer'. A posting is a candidate through ANY of three doors:
    # Geo-screened as they are collected: a trade profile's title matches are overwhelmingly
    # abroad ("Welder" in Ireland), and letting them fill the candidate budget starved every
    # other door — the one job in the candidate's own country never got a slot.
    token_ids = {pid for pid, title, loc in id_titles
                 if (not keywords or keywords & set(_TOKEN_RE.findall((title or "").lower())))
                 and passes_hard_filters(profile, title or "", loc or "", "")[0]}
    from ...domain.skills import RECALL_GENERIC_SKILLS, extract_skills
    from .. import vector_cache
    geo = vector_cache.geo_narrowing(profile)
    vector_ids = vector_cache.similar_posting_ids(
        db, profile.embedding, settings.recall_min_cosine, extra_filter=geo)
    profile_recall_skills = extract_skills(profile.skills or "") - RECALL_GENERIC_SKILLS
    skill_ids = vector_cache.postings_sharing_skills(db, profile_recall_skills)
    # Every door must be geo-screened before it spends candidate budget. The skill and vector
    # doors weren't, so 400 slots filled with postings abroad (a cook in Bansko got Polish
    # "Kucharz" ads) and NOTHING survived the location filter a moment later — the profile came
    # back empty even though its own market had matches.
    if geo is not None and skill_ids:
        loc_by_id = dict((pid, loc) for pid, _t, loc in
                         ((r[0], r[1], r[2]) for r in id_titles) if pid in skill_ids)
        skill_ids = {pid for pid in skill_ids
                     if passes_hard_filters(profile, "", loc_by_id.get(pid) or "", "")[0]}
    cap = settings.recall_max_candidates
    # Budget the candidate slots by CONFIDENCE, then top up. The precise doors go first — skill
    # (shares a real canonical skill) and the thresholded vector door — then the lexical title
    # door, which floods on a generic role token ('engineer' matched ~14k titles for an ML
    # profile) and so must never be uncapped.
    core = skill_ids | vector_ids
    relevant_ids = list(core)[:cap]
    if len(relevant_ids) < cap:
        seen_ids = set(relevant_ids)
        relevant_ids += [pid for pid in token_ids if pid not in seen_ids][:cap - len(relevant_ids)]
    if len(relevant_ids) < cap:
        # Still room: fall back to the NEAREST postings by rank, with no cosine bar. The bar is
        # absolute and was calibrated on IT profiles; short trade/care/hospitality titles sit
        # below it in every language, so those professions recalled nothing at all (measured: a
        # welder scores 0.763 on "Заварчик", 0.833 on "Site Welder", against a 0.87 threshold).
        # This only ever fills slots the confident doors left empty, so IT recall is unchanged.
        # Oversampled and geo-screened: the nearest postings to a trade profile are all abroad,
        # so taking the top `cap` blindly spent the whole budget on rows the location filter
        # discards seconds later. Screening here (same hard-filter logic, title+location only)
        # lets the budget reach postings the candidate could actually take.
        seen_ids = set(relevant_ids)
        need = cap - len(relevant_ids)
        for pid, title, loc in vector_cache.ranked_candidates(
                db, profile.embedding, cap * settings.recall_rank_oversample,
                extra_filter=vector_cache.geo_narrowing(profile)):
            if pid in seen_ids:
                continue
            if not passes_hard_filters(profile, title, loc or "", "")[0]:
                continue
            relevant_ids.append(pid)
            need -= 1
            if need <= 0:
                break
    existing_by_post = {m.posting_id: m for m in db.execute(
        select(Match).where(Match.profile_id == profile.id)).scalars()}
    scored = filtered = matched = 0
    seen: set = set()
    posts = db.execute(select(Posting).where(Posting.id.in_(relevant_ids))
                       .order_by(Posting.first_seen.desc())).scalars() if relevant_ids else []
    for post in posts:
        seen.add(post.id)
        # A match the user can't act on is noise: postings without ANY link never create NEW
        # matches (junk/manually-scaffolded rows). Existing matches (the owner pasted the JD
        # via the manual form) still refresh their score.
        if not (post.apply_url or post.url) and post.id not in existing_by_post:
            continue
        ok, _reason = passes_hard_filters(profile, post.title, post.location, post.description)
        if not ok:
            filtered += 1
            # a match created before a NEWER filter existed must not outlive it (owner saw
            # pre-geo-filter Monzo 'Remote (UK)' matches still in the feed)
            stale = existing_by_post.pop(post.id, None)
            if stale is not None:
                db.delete(stale)
            continue
        if post.requirements is None:
            post.requirements = extract_requirements(post.description or "")
        # A posting with no extractable must/nice used to be dropped outright ("we'd be scoring
        # blind"). Measured on the live index that is 91% of it: the short aggregator ads state
        # DUTIES, not requirements ("Заварчик — заваряване и рязане на метални конструкции"), so
        # the rule was hiding whole professions and the entire Bulgarian market. They are shown
        # now, scored on similarity alone and capped below anything with real evidence.
        if not any(r.get("kind") in ("must", "nice") for r in post.requirements or []):
            if not settings.show_postings_without_requirements:
                filtered += 1
                stale = existing_by_post.pop(post.id, None)
                if stale is not None:
                    db.delete(stale)
                continue
        # freshness, salary, language, seniority and role-family are soft multipliers on the base
        # score — passed as one product (score() applies it after the blend, inside the gate cap)
        _f = soft_factors(profile, post, expectation)
        soft = (_f["freshness"] * _f["salary"] * _f["language"]
                * _f["seniority"] * _f["role_family"] * _f["location"] * _f["qualification"])
        # the posting IS the candidate's kind of role when their target family overlaps the title's
        role_match = bool(profile_families & _role_families(post.title))
        sc, covered, missing = score(ptext, post.description or post.title, post.requirements,
                                     profile_vec=profile.embedding, posting_vec=post.embedding,
                                     sem_weight=settings.semantic_weight,
                                     freshness=soft, skill_years=skill_years,
                                     role_match=role_match,
                                     role_match_floor=settings.role_match_sem_floor,
                                     gate_cap=settings.must_gate_cap or None,
                                     education_level=profile.qualification_level,
                                     sem_only_cap=settings.semantic_only_cap,
                                     title_role_match=_title_names_role(post.title, role_names),
                                     sem_title_cap=settings.semantic_title_cap)
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
    # Zombie sweep: matches whose posting fell out of the recall set are never re-scored above, so
    # one created under an older, laxer filter (e.g. a hybrid role before relocate/commute handling)
    # could outlive it. Re-check each such leftover against the CURRENT hard filters and drop the
    # ones that no longer qualify (or whose posting was retired).
    leftovers = [(pid, stale) for pid, stale in existing_by_post.items() if pid not in seen]
    # ONE query for all leftovers — a per-row db.get() here is a tunnel round-trip each, and a
    # profile that accumulated many matches (an ML Engineer had 526) turned this sweep into ~490
    # round-trips ≈ 80s. Postings gone from the table simply won't appear in the map → dropped.
    zmap = {zp.id: zp for zp in db.execute(
        select(Posting).where(Posting.id.in_([pid for pid, _ in leftovers]))).scalars()} \
        if leftovers else {}
    for post_id, stale in leftovers:
        zp = zmap.get(post_id)
        if zp is None or not getattr(zp, "is_live", True) or not passes_hard_filters(
                profile, zp.title, zp.location, zp.description)[0]:
            db.delete(stale)
            filtered += 1      # a match dropped here IS a filtering event; recall now geo-screens
                               # its doors, so such a posting no longer reaches the scoring loop
                               # to be counted there
    try:
        db.commit()
    except IntegrityError:
        # two overlapping searches for the same profile (double-click) can both pass the
        # existing-Match check and collide on uq_profile_posting — the other run already saved
        # equivalent matches, so losing this commit is harmless. Roll back so the session stays
        # usable for the caller (record_run etc.).
        db.rollback()
        log.info("concurrent search for profile %s — matches saved by the other run", profile.id)
    # LLM double-check of the covered/missing split for the matches the user will actually see
    # (budgeted, cached per match, silently skipped without any provider). `verify=False` skips
    # it here so the caller can run it OFF the request path — the user's search fires it in a
    # background thread instead of paying up to `verify_top_n` (rate-limited) LLM calls inline.
    verified = 0
    if verify:
        from .verify_coverage import verify_top_matches
        verified = verify_top_matches(db, profile)["verified"]
    if stats is not None:
        stats.add(filtered=filtered, scored=scored, matched=matched, llm_verified=verified)
    return {"pool": pool, "filtered": filtered, "scored": scored, "matched": matched,
            "llm_verified": verified}


def run_search(db: Session, profile, boards=None, limit: int | None = None,
               raw_postings=None, stats=None) -> dict:
    """Ingest + score in one call (compatibility path — the daily digest and tests use it).
    The Search-now route calls `search_db` directly and never fetches."""
    ing = ingest_from_sources(db, boards=boards, raw_postings=raw_postings,
                              profiles=[profile], stats=stats)
    res = search_db(db, profile, limit=limit, stats=stats)
    return {"fetched": ing["fetched"], "added": ing["added"], **res}
