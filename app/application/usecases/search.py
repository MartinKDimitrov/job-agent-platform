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
                             karriere_nrw, arbeitnow)
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
FAST_SOURCES = [("dev_bg", dev_bg.fetch), ("remoteok", remoteok.fetch), ("wwr", wwr.fetch),
                ("karriere_nrw", karriere_nrw.fetch),
                ("arbeitnow", arbeitnow.fetch)]
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
                   ("francetravail_targeted", _francetravail_targeted)]


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
    for post in db.execute(q).scalars():
        if post.requirements is None:
            post.requirements = extract_requirements(post.description or "")
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


def search_db(db: Session, profile, limit: int | None = None, stats=None) -> dict:
    """The READ side: score the profile against the postings ALREADY in our index — no network,
    so Search now answers in well under a second. Vectors come precomputed from the rows.

    Query shape matters: the title pre-filter runs over (id, title) pairs only, and full rows
    (description + vector JSON) load just for the relevant few — pulling all columns of the
    whole index measured ~2.5s over the staging tunnel vs ~0.2s this way."""
    keywords = _profile_keywords(profile)
    ptext = profile.as_text()
    from ...domain.salary import parse_salary, posting_salary, salary_factor
    expectation = parse_salary(profile.salary_expectation or "")   # once per search
    if profile.embedding is None:            # cached on the row; cleared on profile edit
        profile.embedding = _as_list(embed_query(profile.embed_text()))
    id_titles = db.execute(select(Posting.id, Posting.title)
                           .where(Posting.is_live.is_(True))).all()
    pool = len(id_titles)
    # HYBRID RECALL (Phase 5): titles alone cut recall — 'Backend' never sees 'Platform
    # Engineer'. A posting is a candidate through ANY of three doors:
    token_ids = {pid for pid, title in id_titles
                 if not keywords or keywords & set(_TOKEN_RE.findall((title or "").lower()))}
    from ...domain.skills import RECALL_GENERIC_SKILLS, extract_skills
    from .. import vector_cache
    vector_ids = vector_cache.similar_posting_ids(
        db, profile.embedding, settings.recall_min_cosine)
    profile_recall_skills = extract_skills(profile.skills or "") - RECALL_GENERIC_SKILLS
    skill_ids = vector_cache.postings_sharing_skills(db, profile_recall_skills)
    relevant_ids = list(token_ids | vector_ids | skill_ids)
    if len(relevant_ids) > settings.recall_max_candidates:
        # guard rail: keep the lexically/skill-matched, trim the loosest vector extras
        core = token_ids | skill_ids
        extras = [pid for pid in vector_ids if pid not in core]
        relevant_ids = list(core) + extras[:max(0, settings.recall_max_candidates - len(core))]
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
            # a match created before a NEWER filter existed must not outlive it (owner saw
            # pre-geo-filter Monzo 'Remote (UK)' matches still in the feed)
            stale = existing_by_post.pop(post.id, None)
            if stale is not None:
                db.delete(stale)
            continue
        if post.requirements is None:
            post.requirements = extract_requirements(post.description or "")
        # Owner rule: without a single must/nice requirement we'd be scoring blind (pure
        # similarity, capped 60%) — such postings never enter the feed, and matches created
        # before this rule (or before an extractor fix) get cleaned up like stale filters.
        if not any(r.get("kind") in ("must", "nice") for r in post.requirements or []):
            filtered += 1
            stale = existing_by_post.pop(post.id, None)
            if stale is not None:
                db.delete(stale)
            continue
        # freshness and the salary signal are both soft multipliers on the base score —
        # passed as one product (score() applies it after the blend, inside the gate cap)
        soft = posting_freshness(post) * salary_factor(
            posting_salary(post), expectation,
            low=settings.salary_low_factor, fit=settings.salary_fit_boost)
        sc, covered, missing = score(ptext, post.description or post.title, post.requirements,
                                     profile_vec=profile.embedding, posting_vec=post.embedding,
                                     sem_weight=settings.semantic_weight,
                                     freshness=soft,
                                     gate_cap=settings.must_gate_cap or None)
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
    # LLM double-check of the covered/missing split for the matches the user will actually
    # see (budgeted, cached per match, silently skipped without any provider).
    from .verify_coverage import verify_top_matches
    ver = verify_top_matches(db, profile)
    if stats is not None:
        stats.add(filtered=filtered, scored=scored, matched=matched,
                  llm_verified=ver["verified"])
    return {"pool": pool, "filtered": filtered, "scored": scored, "matched": matched,
            "llm_verified": ver["verified"]}


def run_search(db: Session, profile, boards=None, limit: int | None = None,
               raw_postings=None, stats=None) -> dict:
    """Ingest + score in one call (compatibility path — the daily digest and tests use it).
    The Search-now route calls `search_db` directly and never fetches."""
    ing = ingest_from_sources(db, boards=boards, raw_postings=raw_postings,
                              profiles=[profile], stats=stats)
    res = search_db(db, profile, limit=limit, stats=stats)
    return {"fetched": ing["fetched"], "added": ing["added"], **res}
