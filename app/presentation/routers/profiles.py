"""Search profiles: CRUD, validation, the scoring view, and the (Phase-1 scaffold) posting form."""
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Profile, Posting, Match
from ...domain.scoring import score
from ...domain.extraction import extract_requirements
from ...application.usecases.search import run_search
from ...application.run_stats import RunStats
from ...data.metrics_repo import record_run
from ..web import page, current_user, redirect, escape

router = APIRouter()

CEFR_LEVELS = ["A2", "B1", "B2", "C1", "C2"]
REMOTE_PREFS = ["remote", "hybrid", "onsite", "any"]


# ---------- form + validation (shared by create and edit) ----------
def _err_box(errors: list[str]) -> str:
    if not errors:
        return ""
    items = "".join(f"<li>{escape(e)}</li>" for e in errors)
    return ("<div class='card' style='border-color:#c0392b;background:#fdecea'>"
            f"<b style='color:#c0392b'>Please fix:</b>"
            f"<ul style='margin:6px 0 0 18px'>{items}</ul></div>")


def _profile_form(action: str, v: dict, heading: str, errors: list[str] | None = None) -> str:
    """Render the profile form prefilled from `v`. Used by both create and edit so the two
    stay in sync and validation can re-render with the user's input preserved."""
    def sel(val, current):
        return " selected" if val == current else ""
    cefr = "".join(f"<option{sel(x, v.get('english_level', 'B2'))}>{x}</option>" for x in CEFR_LEVELS)
    remote = "".join(f"<option{sel(x, v.get('remote_pref', 'remote'))}>{x}</option>" for x in REMOTE_PREFS)
    return f"""{_err_box(errors or [])}<div class='card'><h2>{escape(heading)}</h2>
    <form method='post' action='{action}'>
    <label>Profile name (e.g. "Senior Android")</label>
    <input name='name' required maxlength='255' value="{escape(v.get('name', ''))}">
    <label>Target roles (comma-separated)</label>
    <input name='target_roles' value="{escape(v.get('target_roles', ''))}">
    <label>Skills (comma-separated)</label>
    <textarea name='skills' rows='3'>{escape(v.get('skills', ''))}</textarea>
    <label>Experience (short)</label>
    <textarea name='experience' rows='3'>{escape(v.get('experience', ''))}</textarea>
    <div class='row2'>
      <div><label>Languages</label>
        <input name='languages' value="{escape(v.get('languages', 'Bulgarian, English'))}"></div>
      <div><label>English level (CEFR)</label><select name='english_level'>{cefr}</select></div>
    </div>
    <div class='row2'>
      <div><label>Location preference</label>
        <input name='location_pref' value="{escape(v.get('location_pref', 'Remote / Varna'))}"></div>
      <div><label>Remote preference</label><select name='remote_pref'>{remote}</select></div>
    </div>
    <div class='row2'>
      <div><label>Salary expectation</label>
        <input name='salary_expectation' maxlength='64' value="{escape(v.get('salary_expectation', ''))}"></div>
      <div><label>Min match %</label>
        <input name='min_match' type='number' min='0' max='100' value="{escape(str(v.get('min_match', 65)))}"></div>
    </div>
    <p style='margin-top:12px'><button class='btn'>Save</button>
    <a class='btn gray' href='/'>Cancel</a></p></form></div>"""


def _validate_profile(name, min_match, english_level, remote_pref, salary_expectation):
    """Return (errors, clean_name, clean_min_match). Keeps create and edit consistent."""
    errors: list[str] = []
    name = (name or "").strip()
    if not name:
        errors.append("Profile name is required.")
    elif len(name) > 255:
        errors.append("Profile name is too long (max 255 characters).")
    try:
        mm = int(min_match)
    except (TypeError, ValueError):
        mm = None
    if mm is None or not (0 <= mm <= 100):
        errors.append("Min match must be a whole number between 0 and 100.")
        mm = 65
    if english_level not in CEFR_LEVELS:
        errors.append("English level must be one of A2, B1, B2, C1, C2.")
    if remote_pref not in REMOTE_PREFS:
        errors.append("Remote preference must be remote, hybrid, onsite or any.")
    if len(salary_expectation or "") > 64:
        errors.append("Salary expectation is too long (max 64 characters).")
    return errors, name, mm


# ---------- score / requirement rendering ----------
def _req_text(r) -> str:
    return r.get("text", "") if isinstance(r, dict) else str(r)


def _req_kind(r) -> str:
    return r.get("kind", "must") if isinstance(r, dict) else "must"


def _chip(text: str, color: str, bg: str) -> str:
    return f"<span class='chip' style='color:{color};background:{bg}'>{escape(text)}</span>"


def _gaps_cell(covered, missing) -> str:
    """Show why a posting scored as it did: missing must-haves (red) and nice-to-haves (grey)
    as chips, with a green count of what's covered. Transparency over a bare number."""
    covered = covered or []
    missing = missing or []
    must_miss = [r for r in missing if _req_kind(r) == "must"]
    nice_miss = [r for r in missing if _req_kind(r) == "nice"]
    chips = "".join(_chip(_req_text(r), "#a02020", "#fdecea") for r in must_miss[:6])
    chips += "".join(_chip(_req_text(r), "#555", "#eceff4") for r in nice_miss[:4])
    n_scored = len([r for r in covered if _req_kind(r) != "resp"])
    cov = (f"<div class='chip' style='color:#1e6b2a;background:#e3f4e3'>✓ {n_scored} covered</div>"
           if n_scored else "")
    return (cov + chips) or "<span class='small'>—</span>"


# ---------- routes (order matters: /profiles/new before /profiles/{pid}) ----------
@router.get("/profiles/new", response_class=HTMLResponse)
def profile_new(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    return page(_profile_form("/profiles", {}, "New profile"), u)


@router.post("/profiles")
def profile_create(request: Request, name: str = Form(""), target_roles: str = Form(""),
                   skills: str = Form(""), experience: str = Form(""),
                   languages: str = Form(""), english_level: str = Form("B2"),
                   location_pref: str = Form(""), remote_pref: str = Form("remote"),
                   salary_expectation: str = Form(""), min_match: str = Form("65"),
                   db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    errors, name, mm = _validate_profile(name, min_match, english_level, remote_pref, salary_expectation)
    v = dict(name=name, target_roles=target_roles, skills=skills, experience=experience,
             languages=languages, english_level=english_level, location_pref=location_pref,
             remote_pref=remote_pref, salary_expectation=salary_expectation, min_match=min_match)
    if errors:
        return page(_profile_form("/profiles", v, "New profile", errors), u)
    p = Profile(user_id=u.id, name=name, target_roles=target_roles, skills=skills,
                experience=experience, languages=languages, english_level=english_level,
                location_pref=location_pref, remote_pref=remote_pref,
                salary_expectation=salary_expectation, min_match=mm)
    db.add(p); db.commit(); db.refresh(p)
    return redirect(f"/profiles/{p.id}")


@router.get("/profiles/{pid}/edit", response_class=HTMLResponse)
def profile_edit_form(pid: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return page("<div class='card'>Not found.</div>", u)
    v = dict(name=p.name, target_roles=p.target_roles, skills=p.skills, experience=p.experience,
             languages=p.languages, english_level=p.english_level, location_pref=p.location_pref,
             remote_pref=p.remote_pref, salary_expectation=p.salary_expectation, min_match=p.min_match)
    return page(_profile_form(f"/profiles/{pid}/edit", v, "Edit profile"), u)


@router.post("/profiles/{pid}/edit")
def profile_update(pid: int, request: Request, name: str = Form(""), target_roles: str = Form(""),
                   skills: str = Form(""), experience: str = Form(""),
                   languages: str = Form(""), english_level: str = Form("B2"),
                   location_pref: str = Form(""), remote_pref: str = Form("remote"),
                   salary_expectation: str = Form(""), min_match: str = Form("65"),
                   db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return page("<div class='card'>Not found.</div>", u)
    errors, name, mm = _validate_profile(name, min_match, english_level, remote_pref, salary_expectation)
    v = dict(name=name, target_roles=target_roles, skills=skills, experience=experience,
             languages=languages, english_level=english_level, location_pref=location_pref,
             remote_pref=remote_pref, salary_expectation=salary_expectation, min_match=min_match)
    if errors:
        return page(_profile_form(f"/profiles/{pid}/edit", v, "Edit profile", errors), u)
    p.name, p.target_roles, p.skills = name, target_roles, skills
    p.experience, p.languages, p.english_level = experience, languages, english_level
    p.location_pref, p.remote_pref = location_pref, remote_pref
    p.salary_expectation, p.min_match = salary_expectation, mm
    p.embedding = None  # profile text changed → drop any cached vector
    db.commit()
    return redirect(f"/profiles/{p.id}")


@router.post("/profiles/{pid}/delete")
def profile_delete(pid: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    db.delete(p); db.commit()  # matches cascade via FK ondelete
    return redirect("/")


@router.post("/profiles/{pid}/min_match")
def profile_set_min_match(pid: int, request: Request, min_match: str = Form("65"),
                          db: Session = Depends(get_db)):
    """Lightweight threshold tuner from the list view (no full edit round-trip). This is the
    same min_match that will later filter auto-fetched matches — see ROADMAP onboarding."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    try:
        mm = int(min_match)
    except (TypeError, ValueError):
        mm = p.min_match
    p.min_match = max(0, min(100, mm))
    db.commit()
    return redirect(f"/profiles/{p.id}")


@router.post("/profiles/{pid}/search")
def profile_search(pid: int, request: Request, db: Session = Depends(get_db)):
    """On-demand crawl: fetch from the seed sources, score against this profile, show matches.
    Synchronous for now; the daily background run is Step 16."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    started = datetime.utcnow()
    stats = RunStats()
    err = ""
    try:
        res = run_search(db, p, stats=stats)
    except Exception as e:  # noqa: BLE001 — degrade gracefully, still record the run
        err = str(e)
        res = {"fetched": 0, "added": 0, "filtered": 0, "matched": 0}
    record_run(db, "search_now", stats, started, ok=not err, error=err)
    return redirect(f"/profiles/{p.id}?fetched={res['fetched']}&new={res['added']}"
                    f"&filtered={res['filtered']}&found={res['matched']}")


@router.get("/profiles/{pid}", response_class=HTMLResponse)
def profile_view(pid: int, request: Request, db: Session = Depends(get_db),
                 fetched: int | None = None, new: int | None = None,
                 filtered: int | None = None, found: int | None = None,
                 gen_err: str | None = None):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return page("<div class='card'>Not found.</div>", u)
    # matches above threshold, sorted desc
    q = (select(Match, Posting).join(Posting, Match.posting_id == Posting.id)
         .where(Match.profile_id == p.id, Match.score >= p.min_match)
         .order_by(Match.score.desc()))
    rows = ""
    for m, post in db.execute(q).all():
        apply = (f"<a class='btn green' href='{escape(post.apply_url or post.url)}' target='_blank'>Apply</a>"
                 if (post.apply_url or post.url) else "<span class='small'>—</span>")
        gen = (f"<form method='post' action='/profiles/{p.id}/postings/{post.id}/generate' style='display:inline'>"
               f"<input type='hidden' name='kind' value='cv'>"
               f"<button class='btn gray' title='Generate a tailored CV (uses your AI key)'>CV</button></form> "
               f"<form method='post' action='/profiles/{p.id}/postings/{post.id}/generate' style='display:inline'>"
               f"<input type='hidden' name='kind' value='cover_letter'>"
               f"<button class='btn gray' title='Generate a cover letter (uses your AI key)'>Letter</button></form>")
        rows += (f"<tr><td><b>{m.score:.0f}%</b></td>"
                 f"<td><b>{escape(post.title)}</b><br><span class='small'>{escape(post.company)} · {escape(post.location)}</span></td>"
                 f"<td>{_gaps_cell(m.covered, m.missing)}</td><td>{apply}<br>{gen}</td></tr>")
    rows = rows or "<tr><td colspan='4' class='small'>No matches above threshold yet. Run a search or add a posting below.</td></tr>"

    banner = ""
    if gen_err:
        banner += (f"<div class='card' style='border-color:#c0392b;background:#fdecea'>"
                   f"<b style='color:#c0392b'>Generation failed:</b> {escape(gen_err)}</div>")
    if found is not None:
        filt = f"{filtered} filtered out (seniority/location), " if filtered else ""
        banner += (f"<div class='card' style='background:#e3f4e3;border-color:#2e7d32'>"
                   f"Search complete — fetched {fetched or 0} postings, {new or 0} new, "
                   f"{filt}<b>{found} match(es)</b> above your {p.min_match}% threshold.</div>")

    body = f"""{banner}<div class='card'><h2>{escape(p.name)} <span class='small'>· min {p.min_match}%</span></h2>
    <p class='small'>Target: {escape(p.target_roles)} · {escape(p.remote_pref)} · {escape(p.location_pref)}</p>
    <p><form method='post' action='/profiles/{p.id}/search' style='display:inline'>
      <button class='btn green'>🔎 Search now</button></form>
    <a class='btn gray' href='/profiles/{p.id}/edit'>Edit</a>
    <form method='post' action='/profiles/{p.id}/delete' style='display:inline'
      onsubmit="return confirm('Delete this profile and its matches? This cannot be undone.')">
      <button class='btn' style='background:#c0392b'>Delete</button></form></p>
    <form method='post' action='/profiles/{p.id}/min_match' class='tuner'>
      <label style='margin:0'>Show matches ≥</label>
      <input name='min_match' type='number' min='0' max='100' value='{p.min_match}' style='width:80px'>
      <span class='small'>%</span><button class='btn gray'>Apply</button></form>
    <table><tr><th>Match</th><th>Role / Company</th><th>Gaps (missing)</th><th></th></tr>{rows}</table></div>
    <div class='card'><h3>Add a posting to score</h3>
    <form method='post' action='/profiles/{p.id}/postings'>
      <label>Job URL</label><input name='url' placeholder='https://...'>
      <label>Apply URL (direct, if different)</label><input name='apply_url'>
      <div class='row2'><div><label>Title</label><input name='title'></div>
      <div><label>Company</label><input name='company'></div></div>
      <label>Location</label><input name='location'>
      <label>Description / requirements (paste the JD)</label><textarea name='description' rows='6'></textarea>
      <p style='margin-top:12px'><button class='btn'>Score it</button></p></form>
      <p class='small'>Phase 2 will auto-fetch these from your sources. For now, paste a JD to see the match score.</p>
    </div>"""
    return page(body, u)


@router.post("/profiles/{pid}/postings")
def add_posting(pid: int, request: Request, url: str = Form(""), apply_url: str = Form(""),
                title: str = Form(""), company: str = Form(""), location: str = Form(""),
                description: str = Form(""), db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    chash = hashlib.sha256((url or title + company + description).encode("utf-8")).hexdigest()[:64]
    post = db.execute(select(Posting).where(Posting.content_hash == chash)).scalar_one_or_none()
    if not post:
        reqs = extract_requirements(description)  # rules-based: must/nice/resp, no LLM cost
        post = Posting(title=title, company=company, url=url, apply_url=apply_url,
                       location=location, description=description, requirements=reqs,
                       content_hash=chash)
        db.add(post); db.commit(); db.refresh(post)
    sc, covered, missing = score(p.as_text(), post.description or post.title, post.requirements)
    existing = db.execute(select(Match).where(Match.profile_id == p.id,
                                              Match.posting_id == post.id)).scalar_one_or_none()
    if existing:
        existing.score, existing.covered, existing.missing = sc, covered, missing
    else:
        db.add(Match(profile_id=p.id, posting_id=post.id, score=sc,
                     covered=covered, missing=missing))
    db.commit()
    return redirect(f"/profiles/{p.id}")
