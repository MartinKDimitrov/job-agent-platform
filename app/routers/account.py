"""Account: GDPR data export and account deletion (cascade + typed confirmation)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Profile, Application
from ..web import page, current_user, redirect, escape
from ..activity import get_activity, set_found_job

router = APIRouter()


@router.get("/account", response_class=HTMLResponse)
def account_view(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    profiles = db.execute(select(Profile).where(Profile.user_id == u.id)).scalars().all()
    act = get_activity(db, u.id)
    paused = bool(act and act.found_job)
    if paused:
        status = ("<b style='color:#2e7d32'>Paused</b> — you marked that you found a job, "
                  "so we're not searching for you.")
        btn = ("<input type='hidden' name='value' value='0'>"
               "<button class='btn'>Resume my searches</button>")
    else:
        status = ("<b>Active</b> — we search daily and email you new matches "
                  "(if you're active in the last 5 days).")
        btn = ("<input type='hidden' name='value' value='1'>"
               "<button class='btn green'>🎉 I found a job — pause searches</button>")
    body = f"""<div class='card'><h2>Account</h2>
    <p class='small'>{escape(u.email)} · joined {u.created_at:%Y-%m-%d}</p>
    <p>{len(profiles)} search profile(s).</p>
    <p><a class='btn gray' href='/account/export'>Export my data (JSON)</a></p></div>
    <div class='card'><h3>Job search status</h3><p class='small'>{status}</p>
    <form method='post' action='/account/found-job'>{btn}</form></div>
    <div class='card' style='border-color:#c0392b'>
    <h3 style='color:#c0392b'>Delete account</h3>
    <p class='small'>Permanently deletes your account, profiles, matches and applications.
    This cannot be undone. Type your email address to confirm.</p>
    <form method='post' action='/account/delete'
      onsubmit="return confirm('Permanently delete your account and all your data?')">
      <input name='confirm_email' placeholder="{escape(u.email)}" autocomplete='off'>
      <p style='margin-top:12px'>
        <button class='btn' style='background:#c0392b'>Delete my account</button></p>
    </form></div>"""
    return page(body, u)


@router.post("/account/found-job")
def account_found_job(request: Request, value: str = Form("0"),
                      db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    set_found_job(db, u.id, value == "1")
    return redirect("/account")


@router.get("/account/export")
def account_export(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    profiles = db.execute(select(Profile).where(Profile.user_id == u.id)).scalars().all()
    apps = db.execute(select(Application).where(Application.user_id == u.id)).scalars().all()
    data = {
        "user": {"email": u.email, "name": u.name, "created_at": u.created_at.isoformat()},
        "profiles": [
            {"name": p.name, "target_roles": p.target_roles, "skills": p.skills,
             "experience": p.experience, "languages": p.languages,
             "english_level": p.english_level, "location_pref": p.location_pref,
             "remote_pref": p.remote_pref, "salary_expectation": p.salary_expectation,
             "min_match": p.min_match, "created_at": p.created_at.isoformat()}
            for p in profiles
        ],
        "applications": [
            {"status": a.status, "date_sent": a.date_sent, "reply": a.reply,
             "reply_date": a.reply_date, "next_step": a.next_step,
             "created_at": a.created_at.isoformat()}
            for a in apps
        ],
    }
    return JSONResponse(
        data, headers={"Content-Disposition": "attachment; filename=my-job-agent-data.json"})


@router.post("/account/delete")
def account_delete(request: Request, confirm_email: str = Form(""),
                   db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    if (confirm_email or "").strip().lower() != u.email.lower():
        body = ("<div class='card' style='border-color:#c0392b'>"
                "<b style='color:#c0392b'>The email you typed does not match.</b> "
                "Your account was not deleted. <a href='/account'>Back to account</a></div>")
        return page(body, u)
    db.delete(u); db.commit()  # cascades profiles → matches, plus applications/sources via FKs
    resp = redirect("/")
    resp.delete_cookie("token")
    return resp
