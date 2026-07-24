"""ATS auto-detection (ROADMAP 16б): given a company name (and optionally its careers page),
find which supported ATS hosts its postings and under what slug.

Two complementary strategies, both cheap and polite (a handful of GETs per company):
1. SLUG PROBING — guess likely board slugs from the name and hit each ATS's public JSON
   endpoint. A valid board answers 200 with a jobs payload; a missing one 404s.
2. CAREERS-PAGE SCAN — fetch the careers URL (when known) and look for links/embeds that
   reveal the ATS host (boards.greenhouse.io/<slug>, jobs.lever.co/<slug>, ashbyhq.com/<slug>).

Detection is a build-time/registry tool — it never runs on a user's search path.
"""
from __future__ import annotations

import logging
import re

from .sources.http import fetch_json, fetch_text, post_json

log = logging.getLogger(__name__)


def _probe_greenhouse(slug: str) -> bool:
    j = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return isinstance(j, dict) and "jobs" in j


def _probe_lever(slug: str) -> bool:
    j = fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json", browser=True)
    return isinstance(j, list)


def _probe_ashby(slug: str) -> bool:
    j = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", browser=True)
    return isinstance(j, dict) and "jobs" in j


def _probe_workable(slug: str) -> bool:
    # v3 answers 200 + {"results": [...]} for EXISTING accounts (even with 0 published jobs —
    # future postings then appear automatically), 404 otherwise. POST-only endpoint.
    j = post_json(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", {"query": ""})
    return isinstance(j, dict) and "results" in j


def _probe_teamtailor(slug_or_url: str) -> bool:
    # Works for both `<slug>.teamtailor.com` and custom careers domains (the slug is then the
    # full base URL, produced by the careers-page scan). The tt: namespace is the fingerprint.
    from .sources.teamtailor import base_url
    body = fetch_text(f"{base_url(slug_or_url)}/jobs.rss")
    return bool(body) and "teamtailor.com/locations" in body


def _probe_smartrecruiters(slug: str) -> bool:
    # DANGER: this API answers 200 + {"totalFound": 0} for ANY slug, including gibberish
    # (verified live — a naive existence check registered 105 phantom boards). Only a slug
    # with actual live postings counts as a hit; dormant ones re-probe monthly anyway.
    j = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                   params={"limit": 1})
    return isinstance(j, dict) and int(j.get("totalFound") or 0) > 0


def _probe_recruitee(slug: str) -> bool:
    j = fetch_json(f"https://{slug}.recruitee.com/api/offers/", browser=True)
    return isinstance(j, dict) and "offers" in j


def _probe_personio(slug: str) -> bool:
    for tld in ("de", "com"):
        body = fetch_text(f"https://{slug}.jobs.personio.{tld}/xml")
        if body and "<workzag-jobs" in body:
            return True
    return False


def _probe_workday(base_url: str) -> bool:
    # base_url is the CXS base (…/wday/cxs/{tenant}/{site}); a real board answers the list POST
    from .sources.http import post_json
    j = post_json(f"{base_url.rstrip('/')}/jobs",
                  {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    return isinstance(j, dict) and "jobPostings" in j


# ats name -> "does this slug host a live board there?"
_PROBES: dict[str, callable] = {
    "greenhouse": _probe_greenhouse,
    "lever": _probe_lever,
    "ashby": _probe_ashby,
    "workable": _probe_workable,
    "teamtailor": _probe_teamtailor,
    "smartrecruiters": _probe_smartrecruiters,
    "recruitee": _probe_recruitee,
    "personio": _probe_personio,
    "workday": _probe_workday,
}

# Workday CXS host + site, from a myworkdayjobs URL anywhere on the careers page/SPA config.
# e.g. https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/... ->
#      host=nvidia.wd5.myworkdayjobs.com tenant=nvidia site=NVIDIAExternalCareerSite
_WORKDAY_RE = re.compile(
    r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[\w-]{2,5}/)?([\w-]+)", re.I)

_CAREERS_PATTERNS = [
    ("greenhouse", re.compile(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?[^\"']*for=([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?!api/)([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
    ("personio", re.compile(r"([\w-]+)\.jobs\.personio\.(?:de|com)", re.I)),
]


def slug_guesses(name: str) -> list[str]:
    """Likely board slugs for a company name: 'EGT Digital' -> egtdigital, egt-digital, egt."""
    base = re.sub(r"[^a-z0-9 ]+", "", name.lower()).strip()
    words = base.split()
    if not words:
        return []
    guesses = ["".join(words), "-".join(words)]
    if len(words) > 1:
        guesses.append(words[0])
    return list(dict.fromkeys(g for g in guesses if len(g) >= 3))


def probe_slug(ats: str, slug: str) -> bool:
    """True when `slug` is a live board on `ats` (public JSON answers with a jobs payload)."""
    return _PROBES[ats](slug)


def scan_careers_page(careers_url: str) -> tuple[str, str] | None:
    """Extract (ats, slug) from links/embeds on the company's careers page, if any."""
    html = fetch_text(careers_url)
    if not html:
        return None
    for ats, pat in _CAREERS_PATTERNS:
        m = pat.search(html)
        if m:
            return ats, m.group(1)
    # Workday: the big-enterprise board. Its host+site appears in the careers page/SPA config;
    # the board id is the whole CXS base URL (three parts — tenant, datacenter, site).
    wd = _WORKDAY_RE.search(html)
    if wd:
        tenant, dc, site = wd.group(1), wd.group(2), wd.group(3)
        # skip generic path words that aren't a real site slug
        if site.lower() not in ("en-us", "en", "job", "jobs", "wday"):
            base = f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
            return "workday", base
    # Teamtailor white-labels on the company's OWN domain (careers.mypos.com) — no external
    # link to match, but the page code is full of teamtailor fingerprints. The board id is
    # then the careers site's base URL itself; detect() verifies it via /jobs.rss.
    if "teamtailor" in html.lower():
        from urllib.parse import urlparse
        u = urlparse(careers_url)
        return "teamtailor", f"{u.scheme}://{u.netloc}"
    return None


# hrefs that smell like a careers page, in both languages of our market
_CAREERS_HREF_RE = re.compile(
    r"""href=["']([^"']*(?:career|karier|kariera|jobs|rabota|jobads|vacanc|join-us|
    работа|кариер)[^"']*)["']""", re.I | re.X)
# fallback paths tried directly on the site when the homepage names no careers link
_CAREERS_PATHS = ("/careers", "/career", "/kariera", "/karieri", "/jobs", "/en/careers",
                  "/bg/kariera", "/rabota-pri-nas", "/za-nas/karieri")
_CAREERS_SIGNAL_RE = re.compile(r"карие|career|jobs|работ|позици|vacanc|apply", re.I)


def find_careers_url(website: str) -> str:
    """Find a company's careers page starting from its main site: follow the first
    careers-looking link on the homepage, else try the common paths. Returns '' when
    nothing answers with a careers-looking page."""
    from urllib.parse import urljoin
    website = (website or "").strip().rstrip("/")
    if not website:
        return ""
    html = fetch_text(website) or ""
    candidates = []
    for m in _CAREERS_HREF_RE.finditer(html):
        href = m.group(1)
        # static assets can contain 'career' in their bundle names (Kaufland's CSS did)
        if re.search(r"\.(css|js|png|jpe?g|svg|woff2?|ico|pdf)(\?|$)", href, re.I):
            continue
        candidates.append(urljoin(website + "/", href))
        break
    candidates += [website + p for p in _CAREERS_PATHS]
    for url in dict.fromkeys(candidates):
        page = fetch_text(url)
        if page and _CAREERS_SIGNAL_RE.search(page):
            return url
    return ""


# ---- identity verification (the phantom-board lesson, automated for the EU expansion) ----
# Guessed slugs can hit a SAME-NAMED stranger's board (personio/kbc was a Munich firm, not
# KBC Bulgaria). Policy: a careers-page-derived board is authoritative (the company's own
# site links it); a GUESSED slug is accepted only when the ATS's public API reports the
# organization's display name AND it matches ours. ATSes that expose no name (lever, ashby,
# personio) are careers-page-only — guessing there is structurally unsafe.

def board_display_name(ats: str, slug: str) -> str | None:
    """The organization name as the ATS itself reports it, when the public API exposes one."""
    if ats == "greenhouse":
        j = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        return (j or {}).get("name") if isinstance(j, dict) else None
    if ats == "workable":
        j = fetch_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
        return (j or {}).get("name") if isinstance(j, dict) else None
    if ats == "smartrecruiters":
        j = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{slug}")
        return (j or {}).get("name") if isinstance(j, dict) else None
    if ats == "teamtailor":
        from .sources.teamtailor import base_url
        body = fetch_text(f"{base_url(slug)}/jobs.rss") or ""
        m = re.search(r"<title>([^<]+)</title>", body)
        return m.group(1).strip() if m else None
    if ats == "recruitee":
        j = fetch_json(f"https://{slug}.recruitee.com/api/offers/", browser=True)
        offers = (j or {}).get("offers") if isinstance(j, dict) else None
        return (offers[0].get("company_name") or None) if offers else None
    return None


_NAME_APIS = frozenset({"greenhouse", "workable", "smartrecruiters", "teamtailor", "recruitee"})


# legal-form suffixes that boards append to their display name ("Adyen N.V.", "... GmbH") —
# stripped before comparison so the suffix never decides the match
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(gmbh|ag|se|n ?v|b ?v|inc|ltd|llc|plc|s ?a|s ?r ?l|sp z o ?o|oy|ab|a ?s|aps|"
    r"co|corp|group|holding[s]?)\b\.?", re.I)


def _org_norm(name: str) -> str:
    from ..domain.dedup import normalize_company
    n = normalize_company(name or "")
    n = _LEGAL_SUFFIX_RE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def names_match(expected: str, reported: str) -> bool:
    """Same-organization check on WHOLE tokens. Strict by design: a false reject only means
    one less registration; a false accept poisons the index with a stranger's postings.
    (A difflib-ratio fallback used to live here — it let 'Inter Cars' ≈ 'Inter Carreiras'
    (0.80) and 'Vitamin C' ≈ 'Vitamin Well' (0.76) through: character similarity says
    nothing about being the same organization. Token subset does.)"""
    a, b = _org_norm(expected), _org_norm(reported)
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    # one side's full name contained token-wise in the other ('trade republic' ⊆
    # 'trade republic bank') — but only when the shorter side is substantial: a short
    # single-token brand inside a stranger's longer name ('kbc' ⊆ 'kbc bank muenchen')
    # must not pass on the brand word alone
    short = min(ta, tb, key=lambda s: len(" ".join(s)))
    if len(short) < 2 and len("".join(short)) < 8:
        return False
    return ta <= tb or tb <= ta


def detect_verified(name: str, careers_url: str = "") -> tuple[str, str, str] | None:
    """detect() with the identity gate; returns (ats, slug, via) where via is 'careers' or
    'guess'. Careers-page boards are near-authoritative, but the page can also link SOMEONE
    ELSE'S board (remote.com's customer story handed us greenhouse/openly) — so even those
    must corroborate identity: the board's reported name matches, OR the slug itself is the
    company's name (covers display-name rebrands like Intercom's board reporting 'Fin'), OR
    the ATS has no name API. Guessed slugs always need a matching reported name — and the
    CALLER must treat via='guess' as pending human review: three live rounds proved that a
    matching brand word ('Alta', 'Joya', 'Karma', 'NATIONAL'...) is still no proof of being
    the same organization."""
    if careers_url:
        found = scan_careers_page(careers_url)
        if found:
            ats, slug = found
            if probe_slug(ats, slug):
                reported = board_display_name(ats, slug) if ats in _NAME_APIS else None
                if (reported is None or names_match(name, reported)
                        or names_match(name, slug.replace("-", " "))):
                    return ats, slug, "careers"
                log.info("careers page of %s links %s/%s but the board reports %r — "
                         "someone else's board, skipped", name, ats, slug, reported)
            else:
                log.info("careers page of %s names %s/%s but the board is dead",
                         name, ats, slug)
    for slug in slug_guesses(name):
        for ats in _NAME_APIS:
            if not probe_slug(ats, slug):
                continue
            reported = board_display_name(ats, slug)
            if reported and names_match(name, reported):
                return ats, slug, "guess"
            log.info("identity mismatch for %s: guessed %s/%s, board reports %r — skipped",
                     name, ats, slug, reported)
    return None


def detect(name: str, careers_url: str = "") -> tuple[str, str] | None:
    """Return (ats, slug) for `name`, or None when no supported ATS is found.
    The careers page (when given) wins — it's authoritative; slug probing is the fallback."""
    if careers_url:
        found = scan_careers_page(careers_url)
        if found:
            ats, slug = found
            if probe_slug(ats, slug):        # verify the page's link actually serves jobs
                return ats, slug
            log.info("careers page of %s names %s/%s but the board is dead", name, ats, slug)
    for slug in slug_guesses(name):
        for ats in _PROBES:
            if probe_slug(ats, slug):
                return ats, slug
    return None
