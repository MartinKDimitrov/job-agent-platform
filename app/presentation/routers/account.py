"""Account: GDPR data export and account deletion (cascade + typed confirmation)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Profile, Application
from ..web import page, current_user, redirect, escape
from ...data.activity_repo import get_activity, set_found_job
from ...data.keystore import save_config, get_config, delete_config
from ...data.llm import LLMError, get_provider, list_providers

router = APIRouter()


def _llm_card(db: Session, user_id: int, llm_msg: str = "", llm_ok: bool = True) -> str:
    """BYOK settings card: provider select + key + Test & save. The key is never rendered back
    — only a 'Configured: <provider>' line proves one is stored."""
    cfg = get_config(db, user_id)
    configured = ""
    if cfg:
        p = get_provider(cfg["provider"])
        label = p.label if p else cfg["provider"]
        model = cfg["model"] or "default model"
        configured = (f"<p>Configured: <b>{escape(label)}</b> "
                      f"<span class='small'>({escape(model)})</span></p>"
                      "<form method='post' action='/account/llm/delete' style='display:inline'>"
                      "<button class='btn gray'>Remove key</button></form>")
    msg = ""
    if llm_msg:
        color = "#2e7d32" if llm_ok else "#c0392b"
        msg = f"<p style='color:{color}'><b>{escape(llm_msg)}</b></p>"
    options = "".join(
        f"<option value='{escape(p.name)}'>{escape(p.label)}"
        f"{'' if p.needs_key else ' — no key needed'}</option>" for p in list_providers())
    return f"""<div class='card'><h3>AI generation (bring your own key)</h3>
    <p class='small'>CV and cover-letter generation runs on <b>your</b> LLM account. Recommended
    free options: Google Gemini (aistudio.google.com) or Groq (console.groq.com). Your key is
    stored encrypted, never shown back, and you can remove it any time.</p>
    {configured}{msg}
    <form method='post' action='/account/llm'>
      <div class='row2'>
        <div><label>Provider</label><select name='provider'>{options}</select></div>
        <div><label>Model (optional)</label><input name='model' placeholder='provider default'></div>
      </div>
      <label>API key</label>
      <input name='api_key' type='password' autocomplete='off'
             placeholder='paste your API key (not needed for Ollama)'>
      <p style='margin-top:10px'><button class='btn'>Test &amp; save</button></p>
    </form></div>"""


@router.get("/account", response_class=HTMLResponse)
def account_view(request: Request, db: Session = Depends(get_db),
                 llm: str | None = None, llm_err: str | None = None):
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
    llm_msg, llm_ok = "", True
    if llm == "ok":
        llm_msg = "Connection test passed — your key is saved (encrypted)."
    elif llm == "removed":
        llm_msg = "Key removed."
    elif llm_err:
        llm_msg, llm_ok = llm_err, False
    body = f"""<div class='card'><h2>Account</h2>
    <p class='small'>{escape(u.email)} · joined {u.created_at:%Y-%m-%d}</p>
    <p>{len(profiles)} search profile(s).</p>
    <p><a class='btn gray' href='/account/export'>Export my data (JSON)</a></p></div>
    <div class='card'><h3>Job search status</h3><p class='small'>{status}</p>
    <form method='post' action='/account/found-job'>{btn}</form></div>
    {_llm_card(db, u.id, llm_msg, llm_ok)}
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


@router.post("/account/llm")
def account_llm_save(request: Request, provider: str = Form(""), api_key: str = Form(""),
                     model: str = Form(""), db: Session = Depends(get_db)):
    """Test the key with a tiny real call, then save it encrypted. A key that fails the test is
    never stored — the user finds out immediately, not at generation time."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = get_provider(provider)
    if p is None:
        return redirect("/account?llm_err=Unknown provider.")
    api_key = api_key.strip()
    if p.needs_key and not api_key:
        return redirect("/account?llm_err=This provider requires an API key.")
    try:
        p.generate("You are a health check.", "Reply with the single word: OK",
                   api_key=api_key, model=model.strip())
    except LLMError as e:
        return redirect(f"/account?llm_err={str(e)[:180]}")
    save_config(db, u.id, provider, api_key, model.strip())
    return redirect("/account?llm=ok")


@router.post("/account/llm/delete")
def account_llm_delete(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    delete_config(db, u.id)
    return redirect("/account?llm=removed")


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
