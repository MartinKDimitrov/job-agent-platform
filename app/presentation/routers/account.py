"""Account: GDPR data export and account deletion (cascade + typed confirmation)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Profile, Application
from ..web import page, current_user, redirect, escape
from ..i18n import t, current_lang
from ...data.activity_repo import get_activity, set_found_job
from ...data.keystore import save_config, get_config, delete_config
from ...data.llm import LLMError, get_provider, list_providers

router = APIRouter()

SWITCH_URLS = {"en": "/lang/en", "bg": "/lang/bg"}


def _llm_card(db: Session, user_id: int, llm_msg: str = "", llm_ok: bool = True,
              ui: str = "en") -> str:
    """BYOK settings card: provider select + key + Test & save. The key is never rendered back
    — only a 'Configured: <provider>' line proves one is stored."""
    cfg = get_config(db, user_id)
    configured = ""
    if cfg:
        p = get_provider(cfg["provider"])
        label = p.label if p else cfg["provider"]
        model = cfg["model"] or t("llm.default_model", ui)
        configured = (f"<p>{escape(t('llm.configured', ui))} <b>{escape(label)}</b> "
                      f"<span class='small'>({escape(model)})</span></p>"
                      "<form method='post' action='/account/llm/delete' style='display:inline'>"
                      f"<button class='btn gray'>{escape(t('llm.remove', ui))}</button></form>")
    msg = ""
    if llm_msg:
        color = "#2e7d32" if llm_ok else "#c0392b"
        msg = f"<p style='color:{color}'><b>{escape(llm_msg)}</b></p>"
    options = "".join(
        f"<option value='{escape(p.name)}'>{escape(p.label)}"
        f"{'' if p.needs_key else escape(t('llm.no_key', ui))}</option>" for p in list_providers())
    return f"""<div class='card'><h3>{escape(t('llm.head', ui))}</h3>
    <p class='small'>{escape(t('llm.note', ui))}</p>
    {configured}{msg}
    <form method='post' action='/account/llm'>
      <div class='row2'>
        <div><label>{escape(t('llm.provider', ui))}</label><select name='provider'>{options}</select></div>
        <div><label>{escape(t('llm.model', ui))}</label><input name='model' placeholder='provider default'></div>
      </div>
      <label>{escape(t('llm.key', ui))}</label>
      <input name='api_key' type='password' autocomplete='off'
             placeholder="{escape(t('llm.key_ph', ui))}">
      <p style='margin-top:10px'><button class='btn'>{t('llm.test_save', ui)}</button></p>
    </form></div>"""


@router.get("/account", response_class=HTMLResponse)
def account_view(request: Request, db: Session = Depends(get_db),
                 llm: str | None = None, llm_err: str | None = None):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    ui = current_lang(request)
    profiles = db.execute(select(Profile).where(Profile.user_id == u.id)).scalars().all()
    act = get_activity(db, u.id)
    paused = bool(act and act.found_job)
    if paused:
        status = (f"<b style='color:#2e7d32'>{escape(t('acct.paused_word', ui))}</b> — "
                  f"{escape(t('acct.paused_rest', ui))}")
        btn = ("<input type='hidden' name='value' value='0'>"
               f"<button class='btn'>{escape(t('acct.resume', ui))}</button>")
    else:
        status = (f"<b>{escape(t('acct.active_word', ui))}</b> — "
                  f"{escape(t('acct.active_rest', ui))}")
        btn = ("<input type='hidden' name='value' value='1'>"
               f"<button class='btn green'>{escape(t('acct.pause', ui))}</button>")
    llm_msg, llm_ok = "", True
    if llm == "ok":
        llm_msg = t("acct.llm_ok", ui)
    elif llm == "removed":
        llm_msg = t("acct.llm_removed", ui)
    elif llm_err:
        llm_msg, llm_ok = llm_err, False
    body = f"""<div class='card'><h2>{escape(t('acct.heading', ui))}</h2>
    <p class='small'>{escape(u.email)} · {escape(t('acct.joined', ui))} {u.created_at:%Y-%m-%d}</p>
    <p>{escape(t('acct.profiles', ui).format(n=len(profiles)))}</p>
    <p><a class='btn gray' href='/account/export'>{escape(t('acct.export', ui))}</a></p></div>
    <div class='card'><h3>{escape(t('acct.status_head', ui))}</h3><p class='small'>{status}</p>
    <form method='post' action='/account/found-job'>{btn}</form></div>
    {_llm_card(db, u.id, llm_msg, llm_ok, ui)}
    <div class='card' style='border-color:#c0392b'>
    <h3 style='color:#c0392b'>{escape(t('acct.delete_head', ui))}</h3>
    <p class='small'>{escape(t('acct.delete_note', ui))}</p>
    <form method='post' action='/account/delete'
      onsubmit="return confirm('{t('acct.delete_confirm', ui)}')">
      <input name='confirm_email' placeholder="{escape(u.email)}" autocomplete='off'>
      <p style='margin-top:12px'>
        <button class='btn' style='background:#c0392b'>{escape(t('acct.delete_btn', ui))}</button></p>
    </form></div>"""
    return page(body, u, title=f"{t('acct.heading', ui)} — Job Agent",
                lang=ui, switch_urls=SWITCH_URLS)


@router.post("/account/llm")
def account_llm_save(request: Request, provider: str = Form(""), api_key: str = Form(""),
                     model: str = Form(""), db: Session = Depends(get_db)):
    """Test the key with a tiny real call, then save it encrypted. A key that fails the test is
    never stored — the user finds out immediately, not at generation time."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    ui = current_lang(request)
    p = get_provider(provider)
    if p is None:
        return redirect(f"/account?llm_err={t('llm.err_unknown', ui)}")
    api_key = api_key.strip()
    if p.needs_key and not api_key:
        return redirect(f"/account?llm_err={t('llm.err_key_required', ui)}")
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
        ui = current_lang(request)
        body = ("<div class='card' style='border-color:#c0392b'>"
                f"<b style='color:#c0392b'>{escape(t('acct.email_mismatch', ui))}</b> "
                f"{escape(t('acct.not_deleted', ui))} "
                f"<a href='/account'>{escape(t('acct.back', ui))}</a></div>")
        return page(body, u, lang=ui, switch_urls=SWITCH_URLS)
    db.delete(u); db.commit()  # cascades profiles → matches, plus applications/sources via FKs
    resp = redirect("/")
    resp.delete_cookie("token")
    return resp
