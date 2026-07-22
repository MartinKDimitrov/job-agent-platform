"""Public, indexable jobs pages — the organic-traffic engine (ROADMAP steps 29/31, M3).

/jobs  +  /bg/jobs             — the GENERAL public showcase: diverse recent openings, general
                                 copy and Q&A, links to the profession pages, register CTA.
/jobs/{occupation_id}          — profession SEO landing page (EN), deliberately targeted copy
/bg/jobs/{occupation_id}       — Bulgarian variant, hreflang-paired

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
    for p in db.execute(select(Posting).order_by(Posting.first_seen.desc())).scalars().all():
        title_toks = set(_TOKEN_RE.findall((p.title or "").lower()))
        if toks & title_toks:
            matched.append(p)
    return len(matched), matched[:limit]


_COPY = {
    "en": {
        "jobs_title": "Jobs — Bulgaria & remote | Job Agent",
        "jobs_h1": "Jobs — Bulgaria & remote",
        "jobs_sub": "We track open positions across job boards and company career sites, and "
                    "score each one against your skills.",
        "jobs_tracked": "open positions tracked right now",
        "recent": "Recently seen openings",
        "byprof": "Browse by profession",
        "h1": "{occ} jobs — Bulgaria & remote",
        "meta": "Open {occ} positions in Bulgaria and remote, scored against your skills.",
        "tracked": "open positions tracked right now",
        "sample": "Recently seen openings",
        "skills": "Typical skills employers ask for",
        "cta_h": "See which of these match YOU",
        "cta_p": "Create a free profile in ~30 seconds — we score every opening against your "
                 "skills and show your matches with a direct apply link.",
        "cta_btn": "Get started — it's free",
        "q1_h": "How does Job Agent work?",
        "q1_p": "You describe your skills once. We scan job sources daily, score every opening "
                "against your profile, and email you only the new matches.",
        "q2_h": "Is it free?",
        "q2_p": "Yes — creating a profile and seeing your matches is free.",
    },
    "bg": {
        "jobs_title": "Работа — България и remote | Job Agent",
        "jobs_h1": "Работа — България и remote",
        "jobs_sub": "Следим отворените позиции в обявните платформи и кариерните сайтове и "
                    "оценяваме всяка спрямо твоите умения.",
        "jobs_tracked": "отворени позиции в момента",
        "recent": "Скорошни обяви",
        "byprof": "Разгледай по професия",
        "h1": "Работа като {occ} — България и remote",
        "meta": "Отворени позиции за {occ} в България и дистанционно, оценени спрямо твоите умения.",
        "tracked": "отворени позиции в момента",
        "sample": "Скорошни обяви",
        "skills": "Типични умения, които работодателите търсят",
        "cta_h": "Виж кои от тях пасват на ТЕБ",
        "cta_p": "Създай безплатен профил за ~30 секунди — оценяваме всяка обява спрямо твоите "
                 "умения и ти показваме съвпаденията с директен линк за кандидатстване.",
        "cta_btn": "Започни безплатно",
        "q1_h": "Как работи Job Agent?",
        "q1_p": "Описваш уменията си веднъж. Ние сканираме източниците ежедневно, оценяваме "
                "всяка обява спрямо профила ти и ти пращаме само новите съвпадения.",
        "q2_h": "Безплатно ли е?",
        "q2_p": "Да — създаването на профил и виждането на съвпаденията е безплатно.",
    },
}


def _sample_rows(sample: list[Posting], cta: str) -> str:
    """title + company only; equal-width right-aligned CTA buttons (owner feedback)."""
    return "".join(
        f"<div class='job-row'><div class='info'><div class='t'>{escape(p.title)}</div>"
        f"<div class='m'>{escape(p.company)}</div></div>"
        f"<a class='btn gray small job-cta' href='/register'>{escape(cta)}</a></div>"
        for p in sample)


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
    c = _COPY[lang]
    postings = db.execute(
        select(Posting).order_by(Posting.first_seen.desc()).limit(6)).scalars().all()
    total = len(db.execute(select(Posting.id)).all())
    label = "bg" if lang == "bg" else "en"
    prof_links = "".join(
        f"<a class='tab' href='{'/bg' if lang == 'bg' else ''}/jobs/{escape(o['id'])}' "
        f"style='margin:0 6px 10px 0'>{escape(o[label])}</a>" for o in OCCUPATIONS)
    sample_html = f"<h2>{escape(c['recent'])}</h2>{_sample_rows(postings, c['cta_btn'])}" \
        if postings else ""
    en_path, bg_path = "/jobs", "/bg/jobs"
    path = bg_path if lang == "bg" else en_path
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
                switch_urls={"en": en_path, "bg": bg_path},
                hreflang=[("en", abs_url(en_path)), ("bg", abs_url(bg_path)),
                          ("x-default", abs_url(en_path))])


def _occupation_page(request: Request, db: Session, occupation_id: str, lang: str):
    """Profession SEO landing page — deliberately targeted headline (it ranks for
    'работа като X' queries); the general showcase lives at /jobs."""
    occ = by_id(occupation_id)
    if occ is None:
        return page("<div class='card'>Not found.</div>", None)
    c = _COPY[lang]
    occ_name = occ["bg"] if lang == "bg" else occ["en"]
    count, sample = _matching_postings(db, occ)

    sample_html = (f"<h2>{escape(c['sample'])}</h2>{_sample_rows(sample, c['cta_btn'])}"
                   if sample else "")
    # typical-skills card is for signed-in visitors only (owner decision)
    u = current_user(request, db)
    skills_html = ""
    if u:
        chips = "".join(f"<span class='chip'>{escape(s)}</span>" for s in occ["skills"])
        skills_html = (f"<div class='card'><h3>{escape(c['skills'])}</h3>"
                       f"<div style='display:flex;flex-wrap:wrap;gap:8px'>{chips}</div></div>")

    en_path = f"/jobs/{occupation_id}"
    bg_path = f"/bg/jobs/{occupation_id}"
    path = bg_path if lang == "bg" else en_path
    hreflang = [("en", abs_url(en_path)), ("bg", abs_url(bg_path)),
                ("x-default", abs_url(en_path))]
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
                switch_urls={"en": en_path, "bg": bg_path}, hreflang=hreflang)


@router.get("/jobs", response_class=HTMLResponse)
def jobs_index_en(db: Session = Depends(get_db)):
    return _jobs_index(db, "en")


@router.get("/bg/jobs", response_class=HTMLResponse)
def jobs_index_bg(db: Session = Depends(get_db)):
    return _jobs_index(db, "bg")


@router.get("/jobs/{occupation_id}", response_class=HTMLResponse)
def job_page_en(occupation_id: str, request: Request, db: Session = Depends(get_db)):
    return _occupation_page(request, db, occupation_id, "en")


@router.get("/bg/jobs/{occupation_id}", response_class=HTMLResponse)
def job_page_bg(occupation_id: str, request: Request, db: Session = Depends(get_db)):
    return _occupation_page(request, db, occupation_id, "bg")