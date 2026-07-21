"""Public, indexable profession pages — the organic-traffic engine (ROADMAP steps 29/31, M3).

/jobs                      — index of professions (EN)
/jobs/{occupation_id}      — e.g. /jobs/android-developer (EN)
/bg/jobs/{occupation_id}   — Bulgarian variant, hreflang-paired with the EN page

Content policy (deliberate): we show live COUNTS and sample titles (title + company only) —
never full postings or apply links publicly. The value ("see your matches, apply") sits behind
the free registration; the pages still carry genuine content (typical skills from the taxonomy,
live numbers, Q&A) so they earn indexing and AdSense eligibility.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Posting
from ...domain.taxonomy import OCCUPATIONS, by_id
from ..seo import site_jsonld, abs_url
from ..web import page, escape

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
        "jobs_title": "Jobs by profession — Job Agent",
        "jobs_h1": "Jobs by profession",
        "jobs_sub": "Pick your profession — we track open positions across job boards and "
                    "company career sites, and score each one against your skills.",
        "h1": "{occ} jobs — Bulgaria & remote",
        "meta": "Open {occ} positions in Bulgaria and remote, scored against your skills. "
                "Typical skills, live openings, and a direct path to apply.",
        "tracked": "open positions tracked right now",
        "sample": "Recently seen openings",
        "skills": "Typical skills employers ask for",
        "cta_h": "See which of these match YOU",
        "cta_p": "Create a free profile in ~30 seconds — we score every opening against your "
                 "skills and show your matches with a direct apply link.",
        "cta_btn": "Get started — it's free",
        "q1_h": "How does Job Agent work for {occ_low} roles?",
        "q1_p": "You describe your skills once. We scan job sources daily, score every {occ_low} "
                "opening against your profile, and email you only the new matches.",
        "q2_h": "Is it free?",
        "q2_p": "Yes — creating a profile and seeing your matches is free.",
    },
    "bg": {
        "jobs_title": "Работа по професии — Job Agent",
        "jobs_h1": "Работа по професии",
        "jobs_sub": "Избери професията си — следим отворените позиции в обявните платформи и "
                    "кариерните сайтове и оценяваме всяка спрямо твоите умения.",
        "h1": "Работа като {occ} — България и remote",
        "meta": "Отворени позиции за {occ} в България и дистанционно, оценени спрямо твоите "
                "умения. Типични изисквания, актуални бройки и директен път за кандидатстване.",
        "tracked": "отворени позиции в момента",
        "sample": "Скорошни обяви",
        "skills": "Типични умения, които работодателите търсят",
        "cta_h": "Виж кои от тях пасват на ТЕБ",
        "cta_p": "Създай безплатен профил за ~30 секунди — оценяваме всяка обява спрямо твоите "
                 "умения и ти показваме съвпаденията с директен линк за кандидатстване.",
        "cta_btn": "Започни безплатно",
        "q1_h": "Как работи Job Agent за позиции {occ_low}?",
        "q1_p": "Описваш уменията си веднъж. Ние сканираме източниците ежедневно, оценяваме "
                "всяка обява за {occ_low} спрямо профила ти и ти пращаме само новите съвпадения.",
        "q2_h": "Безплатно ли е?",
        "q2_p": "Да — създаването на профил и виждането на съвпаденията е безплатно.",
    },
}


def _occupation_page(db: Session, occupation_id: str, lang: str):
    occ = by_id(occupation_id)
    if occ is None:
        return page("<div class='card'>Not found.</div>", None)
    c = _COPY[lang]
    occ_name = occ["bg"] if lang == "bg" else occ["en"]
    count, sample = _matching_postings(db, occ)

    sample_html = ""
    if sample:
        rows = "".join(
            f"<div class='doc-row'><div class='info'><div class='t'>{escape(p.title)}</div>"
            f"<div class='m'>{escape(p.company)}</div></div>"
            f"<a class='btn gray small' href='/register'>{escape(c['cta_btn'])}</a></div>"
            for p in sample)
        sample_html = f"<h2>{escape(c['sample'])}</h2>{rows}"

    skills_html = "".join(f"<span class='chip'>{escape(s)}</span>" for s in occ["skills"])
    en_path = f"/jobs/{occupation_id}"
    bg_path = f"/bg/jobs/{occupation_id}"
    path = bg_path if lang == "bg" else en_path
    hreflang = [("en", abs_url(en_path)), ("bg", abs_url(bg_path)), ("x-default", abs_url(en_path))]

    body = f"""<div class='page-head'><div class='title-block'>
    <h1>{escape(c['h1'].format(occ=occ_name))}</h1>
    <p class='sub'><b>{count}</b> {escape(c['tracked'])}</p></div></div>
    <div class='card'><h3>{escape(c['skills'])}</h3>
    <div style='display:flex;flex-wrap:wrap;gap:8px'>{skills_html}</div></div>
    {sample_html}
    <div class='card center'><h2 class='mt-0'>{escape(c['cta_h'])}</h2>
    <p class='small'>{escape(c['cta_p'])}</p>
    <a class='btn big' href='/register'>{escape(c['cta_btn'])}</a></div>
    <div class='qa'>
    <div class='q'><h4>{escape(c['q1_h'].format(occ_low=occ_name))}</h4>
    <p>{escape(c['q1_p'].format(occ_low=occ_name))}</p></div>
    <div class='q'><h4>{escape(c['q2_h'])}</h4><p>{escape(c['q2_p'])}</p></div>
    </div>"""
    return page(body, None,
                title=c["h1"].format(occ=occ_name) + " — Job Agent",
                description=c["meta"].format(occ=occ_name),
                path=path, noindex=False, head_extra=site_jsonld(), lang=lang,
                switch_urls={"en": en_path, "bg": bg_path}, hreflang=hreflang)


@router.get("/jobs", response_class=HTMLResponse)
def jobs_index(db: Session = Depends(get_db)):
    c = _COPY["en"]
    cards = "".join(
        f"<a class='tab' href='/jobs/{escape(o['id'])}' style='margin:0 6px 10px 0'>"
        f"{escape(o['en'])}</a>" for o in OCCUPATIONS)
    body = f"""<div class='page-head'><div class='title-block'>
    <h1>{escape(c['jobs_h1'])}</h1><p class='sub'>{escape(c['jobs_sub'])}</p></div></div>
    <div class='card'><div class='profile-tabs' style='flex-wrap:wrap'>{cards}</div></div>"""
    return page(body, None, title=c["jobs_title"],
                description=c["jobs_sub"], path="/jobs", noindex=False,
                head_extra=site_jsonld(), lang="en",
                switch_urls={"en": "/jobs", "bg": "/jobs"})


@router.get("/jobs/{occupation_id}", response_class=HTMLResponse)
def job_page_en(occupation_id: str, db: Session = Depends(get_db)):
    return _occupation_page(db, occupation_id, "en")


@router.get("/bg/jobs/{occupation_id}", response_class=HTMLResponse)
def job_page_bg(occupation_id: str, db: Session = Depends(get_db)):
    return _occupation_page(db, occupation_id, "bg")