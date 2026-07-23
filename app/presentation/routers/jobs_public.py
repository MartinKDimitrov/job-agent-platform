"""Public, indexable jobs pages — the organic-traffic engine (ROADMAP steps 29/31, M3).

/jobs + /{lang}/jobs           — the GENERAL public showcase: diverse recent openings, general
                                 copy and Q&A, links to the profession pages, register CTA.
/jobs/{occupation_id}          — profession SEO landing page (EN), deliberately targeted copy
/{lang}/jobs/{occupation_id}   — localized variants, hreflang-paired across all 13 languages
                                 (copy lives in the translation catalogs as pub.* keys)

Content policy (deliberate): live COUNTS and sample titles (title + company only) — never full
postings or apply links publicly; the value sits behind the free registration. The typical-
skills card renders only for logged-in visitors (owner decision).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Posting
from ...domain.taxonomy import OCCUPATIONS, by_id
from ..i18n import LANGS, t
from ..seo import site_jsonld, abs_url
from ..web import page, current_user, escape

router = APIRouter()

_TOKEN_RE = re.compile(r"[a-z0-9\+\#\.]+")
# Generic role words shared by every profession title — they must not drive matching
# ("QA Engineer" must not count every "... Engineer" posting).
_ROLE_GENERIC = {"developer", "engineer", "specialist", "scientist", "manager",
                 "administrator", "designer", "analyst", "master", "lead"}


def _distinct_tokens(occ: dict) -> set[str]:
    toks = {t for t in _TOKEN_RE.findall(occ["en"].lower())} - _ROLE_GENERIC
    return toks or {t for t in _TOKEN_RE.findall(occ["en"].lower())}


def _matching_postings(db: Session, occ: dict, limit: int = 6) -> tuple[int, list[Posting]]:
    """Count + sample of tracked postings whose title shares a distinctive occupation token.
    In-memory filter — the postings table is small; revisit with SQL when it grows."""
    toks = _distinct_tokens(occ)
    matched = []
    for p in db.execute(select(Posting).where(Posting.is_live.is_(True))
                        .order_by(Posting.first_seen.desc())).scalars().all():
        title_toks = set(_TOKEN_RE.findall((p.title or "").lower()))
        if toks & title_toks:
            matched.append(p)
    return len(matched), matched[:limit]


def _sample_rows(sample: list[Posting], cta: str) -> str:
    """title + company only; equal-width right-aligned CTA buttons (owner feedback)."""
    return "".join(
        f"<div class='job-row'><div class='info'><div class='t'>{escape(p.title)}</div>"
        f"<div class='m'>{escape(p.company)}</div></div>"
        f"<a class='btn gray small job-cta' href='/register'>{escape(cta)}</a></div>"
        for p in sample)


_COPY_KEYS = ("jobs_title", "jobs_h1", "jobs_sub", "jobs_tracked", "recent", "byprof",
              "h1", "meta", "tracked", "sample", "skills", "cta_h", "cta_p", "cta_btn",
              "q1_h", "q1_p", "q2_h", "q2_p", "expanding")


def _copy(lang: str) -> dict:
    """Public-page copy for `lang` from the shared catalogs (pub.* keys, EN fallback)."""
    return {k: t(f"pub.{k}", lang) for k in _COPY_KEYS}


def _jobs_paths(occupation_id: str | None = None) -> dict[str, str]:
    """lang -> language-prefixed public path (/jobs is English, /{lang}/jobs otherwise)."""
    tail = f"/jobs/{occupation_id}" if occupation_id else "/jobs"
    return {code: (tail if code == "en" else f"/{code}{tail}") for code in LANGS}


def _hreflang(paths: dict[str, str]) -> list[tuple[str, str]]:
    return ([(code, abs_url(p)) for code, p in paths.items()]
            + [("x-default", abs_url(paths["en"]))])


def _qa_block(c: dict) -> str:
    return (f"<div class='qa'><div class='q'><h4>{escape(c['q1_h'])}</h4>"
            f"<p>{escape(c['q1_p'])}</p></div>"
            f"<div class='q'><h4>{escape(c['q2_h'])}</h4><p>{escape(c['q2_p'])}</p></div></div>")


def _cta_card(c: dict) -> str:
    return (f"<div class='card center'><h2 class='mt-0'>{escape(c['cta_h'])}</h2>"
            f"<p class='small'>{escape(c['cta_p'])}</p>"
            f"<a class='btn big' href='/register'>{escape(c['cta_btn'])}</a></div>")


def _jobs_index(db: Session, lang: str):
    """The general public showcase: diverse recent openings + profession links (SEO landers)."""
    c = _copy(lang)
    postings = db.execute(
        select(Posting).where(Posting.is_live.is_(True))
        .order_by(Posting.first_seen.desc()).limit(6)).scalars().all()
    total = len(db.execute(select(Posting.id).where(Posting.is_live.is_(True))).all())
    prefix = "" if lang == "en" else f"/{lang}"
    prof_links = "".join(
        f"<a class='tab' href='{prefix}/jobs/{escape(o['id'])}' "
        f"style='margin:0 6px 10px 0'>{escape(o.get(lang) or o['en'])}</a>" for o in OCCUPATIONS)
    sample_html = f"<h2>{escape(c['recent'])}</h2>{_sample_rows(postings, c['cta_btn'])}" \
        if postings else ""
    paths = _jobs_paths()
    path = paths[lang]
    body = f"""<div class='page-head'><div class='title-block'>
    <h1>{escape(c['jobs_h1'])}</h1>
    <p class='sub'><b>{total}</b> {escape(c['jobs_tracked'])} · {escape(c['jobs_sub'])}</p>
    </div></div>
    {sample_html}
    {_cta_card(c)}
    <div class='card'><h3>{escape(c['byprof'])}</h3>
    <div class='profile-tabs' style='flex-wrap:wrap'>{prof_links}</div></div>
    {_qa_block(c)}"""
    return page(body, None, title=c["jobs_title"], description=c["jobs_sub"],
                path=path, noindex=False, head_extra=site_jsonld(), lang=lang,
                switch_urls=paths, hreflang=_hreflang(paths))


def _occupation_page(request: Request, db: Session, occupation_id: str, lang: str):
    """Profession SEO landing page — deliberately targeted headline (it ranks for
    'работа като X' queries); the general showcase lives at /jobs."""
    occ = by_id(occupation_id)
    if occ is None:
        return page(f"<div class='card'>{escape(t('app.not_found', lang))}</div>",
                    None, lang=lang)
    c = _copy(lang)
    occ_name = occ.get(lang) or occ["en"]
    count, sample = _matching_postings(db, occ)

    # A public page saying "0 open positions" reads as broken (owner feedback). When the
    # occupation-filtered set is empty, fall back to the latest openings across all professions
    # with an honest "expanding sources" note — and lead with the TOTAL tracked count instead.
    note = ""
    if count == 0:
        sample = db.execute(
            select(Posting).where(Posting.is_live.is_(True))
            .order_by(Posting.first_seen.desc()).limit(6)).scalars().all()
        count = len(db.execute(select(Posting.id).where(Posting.is_live.is_(True))).all())
        note = f"<p class='small'>{escape(c['expanding'])}</p>"

    sample_html = (f"<h2>{escape(c['sample'])}</h2>{note}{_sample_rows(sample, c['cta_btn'])}"
                   if sample else "")
    # typical-skills card is for signed-in visitors only (owner decision)
    u = current_user(request, db)
    skills_html = ""
    if u:
        chips = "".join(f"<span class='chip'>{escape(s)}</span>" for s in occ["skills"])
        skills_html = (f"<div class='card'><h3>{escape(c['skills'])}</h3>"
                       f"<div style='display:flex;flex-wrap:wrap;gap:8px'>{chips}</div></div>")

    paths = _jobs_paths(occupation_id)
    path = paths[lang]
    body = f"""<div class='page-head'><div class='title-block'>
    <h1>{escape(c['h1'].format(occ=occ_name))}</h1>
    <p class='sub'><b>{count}</b> {escape(c['tracked'])}</p></div></div>
    {skills_html}
    {sample_html}
    {_cta_card(c)}
    {_qa_block(c)}"""
    return page(body, u,
                title=c["h1"].format(occ=occ_name) + " — Job Agent",
                description=c["meta"].format(occ=occ_name),
                path=path, noindex=False, head_extra=site_jsonld(), lang=lang,
                switch_urls=paths, hreflang=_hreflang(paths))


@router.get("/jobs", response_class=HTMLResponse)
def jobs_index_en(db: Session = Depends(get_db)):
    return _jobs_index(db, "en")


@router.get("/jobs/{occupation_id}", response_class=HTMLResponse)
def job_page_en(occupation_id: str, request: Request, db: Session = Depends(get_db)):
    return _occupation_page(request, db, occupation_id, "en")


# Localized routes registered explicitly per language (no catch-all /{lang} segment —
# it would swallow unrelated paths). Same handlers, language from the URL prefix.
def _make_index_handler(code: str):
    def localized_index(db: Session = Depends(get_db)):
        return _jobs_index(db, code)
    localized_index.__name__ = f"jobs_index_{code}"
    return localized_index


def _make_occ_handler(code: str):
    def localized_page(occupation_id: str, request: Request, db: Session = Depends(get_db)):
        return _occupation_page(request, db, occupation_id, code)
    localized_page.__name__ = f"job_page_{code}"
    return localized_page


for _code in LANGS:
    if _code != "en":
        router.get(f"/{_code}/jobs", response_class=HTMLResponse)(_make_index_handler(_code))
        router.get(f"/{_code}/jobs/{{occupation_id}}",
                   response_class=HTMLResponse)(_make_occ_handler(_code))