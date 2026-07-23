"""Generated documents: create (CV / cover letter for a match), view, list. Owner-checked."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Document, Posting, Match, Profile
from ...application.usecases.generate_document import (GenerationError, NoProviderConfigured,
                                                       generate_document)
from ..web import page, current_user, redirect, escape
from ..i18n import t, current_lang
from ..doc_template import render_document_html

router = APIRouter()

from ..i18n import SWITCH_URLS  # noqa: F811 — cookie-based switcher, all languages

# Print titles follow the DOCUMENT's language (what the recipient reads), not the UI language.
_KIND_TITLE = {"en": {"cv": "Curriculum Vitae", "cover_letter": "Cover Letter"},
               "bg": {"cv": "Автобиография", "cover_letter": "Мотивационно писмо"}}


def _kind_label(kind: str, ui: str) -> str:
    return t("docs.kind_cv", ui) if kind == "cv" else (
        t("docs.kind_letter", ui) if kind == "cover_letter" else kind)


def _profile_for(db: Session, user_id: int, posting_id: int | None) -> Profile | None:
    """The user's profile matched to this posting (for regenerate buttons). Documents don't
    store the profile, so we resolve it through the Match table."""
    if not posting_id:
        return None
    return db.execute(
        select(Profile).join(Match, Match.profile_id == Profile.id)
        .where(Profile.user_id == user_id, Match.posting_id == posting_id)
    ).scalars().first()


@router.post("/profiles/{pid}/postings/{posting_id}/generate")
def generate(pid: int, posting_id: int, request: Request,
             kind: str = Form("cv"), lang: str = Form("en"),
             db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    try:
        doc = generate_document(db, u, pid, posting_id, kind=kind, lang=lang)
    except NoProviderConfigured:
        # no key and no free lane: ask for the key exactly when it's needed (owner request)
        return redirect("/account?llm_needed=1")
    except GenerationError as e:
        return redirect(f"/profiles/{pid}?gen_err={str(e)[:180]}")
    return redirect(f"/documents/{doc.id}")


@router.get("/documents", response_class=HTMLResponse)
def documents_list(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    ui = current_lang(request)
    docs = db.execute(select(Document, Posting)
                      .outerjoin(Posting, Document.posting_id == Posting.id)
                      .where(Document.user_id == u.id)
                      .order_by(Document.created_at.desc())).all()
    rows = "".join(
        f"<tr><td><a href='/documents/{d.id}'>{escape(_kind_label(d.kind, ui))} "
        f"({escape(d.lang.upper())})</a></td>"
        f"<td>{escape(p.title if p else t('docs.removed', ui))}"
        f"<br><span class='small'>{escape(p.company if p else '')}</span></td>"
        f"<td class='small'>{d.created_at:%Y-%m-%d %H:%M}</td></tr>"
        for d, p in docs
    ) or f"<tr><td colspan='3' class='small'>{escape(t('docs.none', ui))}</td></tr>"
    body = (f"<div class='card'><h2>{escape(t('docs.my', ui))}</h2>"
            f"<table><tr><th>{escape(t('docs.document', ui))}</th>"
            f"<th>{escape(t('docs.job', ui))}</th>"
            f"<th>{escape(t('docs.created', ui))}</th></tr>{rows}</table></div>")
    return page(body, u, title=f"{t('docs.my', ui)} — Job Agent",
                lang=ui, switch_urls=SWITCH_URLS)


@router.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_view(doc_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    ui = current_lang(request)
    d = db.get(Document, doc_id)
    if d is None or d.user_id != u.id:
        return page(f"<div class='card'>{escape(t('app.not_found', ui))}</div>", u,
                    lang=ui, switch_urls=SWITCH_URLS)
    post = db.get(Posting, d.posting_id) if d.posting_id else None
    job = (f"{escape(post.title)} — {escape(post.company)}" if post
           else escape(t("docs.removed", ui)))
    apply_btn = (f"<a class='btn green' href='{escape(post.apply_url or post.url)}' "
                 f"target='_blank'>{escape(t('app.apply', ui))}</a>"
                 if post and (post.apply_url or post.url) else "")
    # regenerate controls: resolve the profile via the Match table (documents don't store it)
    regen = ""
    prof = _profile_for(db, u.id, d.posting_id)
    if prof and post:
        other_lang = "bg" if d.lang == "en" else "en"
        other_kind = "cover_letter" if d.kind == "cv" else "cv"
        busy = ("onsubmit=\"var b=this.querySelector('button');"
                f"setTimeout(function(){{b.disabled=true;b.textContent='{t('app.generating', ui)}';}},0);\"")
        regen = (
            f"<form method='post' action='/profiles/{prof.id}/postings/{post.id}/generate' style='display:inline' {busy}>"
            f"<input type='hidden' name='kind' value='{escape(d.kind)}'>"
            f"<input type='hidden' name='lang' value='{other_lang}'>"
            f"<button class='btn gray'>{escape(t('docs.regen_in', ui).format(lang=other_lang.upper()))}</button></form> "
            f"<form method='post' action='/profiles/{prof.id}/postings/{post.id}/generate' style='display:inline' {busy}>"
            f"<input type='hidden' name='kind' value='{other_kind}'>"
            f"<input type='hidden' name='lang' value='{escape(d.lang)}'>"
            f"<button class='btn gray'>{escape(t('docs.other_for', ui).format(kind=_kind_label(other_kind, ui)))}</button></form>")
    saved_note = (f"<p class='small' style='color:var(--green)'><b>{escape(t('docs.saved_word', ui))}</b> "
                  f"{escape(t('docs.saved_rest', ui))}</p>"
                  if request.query_params.get("saved") else "")
    body = f"""<div class='card'>
    <h2>{escape(_kind_label(d.kind, ui))} <span class='small'>· {escape(d.lang.upper())} ·
    {escape(d.provider)}/{escape(d.model)} · prompt {escape(d.prompt_version)}</span></h2>
    <p class='small'>{escape(t('docs.for', ui))} {job}</p>
    <p class='small'><b>{escape(t('docs.review_word', ui))}</b> — {escape(t('docs.review_rest', ui))}</p>
    {saved_note}
    <form method='post' action='/documents/{d.id}/save'>
    <textarea name='content' rows='24' style='font-family:Georgia,serif'>{escape(d.content)}</textarea>
    <p style='margin-top:12px'>
    <button class='btn green'>{escape(t('docs.save', ui))}</button>
    <a class='btn' href='/documents/{d.id}/print' target='_blank'>{escape(t('docs.download', ui))}</a>
    {apply_btn}</p></form>
    <p style='margin-top:12px'>{regen}
    <a class='btn gray small' href='/documents'>{escape(t('docs.my', ui))}</a></p></div>"""
    return page(body, u, title=f"{_kind_label(d.kind, ui)} — Job Agent",
                lang=ui, switch_urls=SWITCH_URLS)


@router.post("/documents/{doc_id}/save")
def document_save(doc_id: int, request: Request, content: str = Form(""),
                  db: Session = Depends(get_db)):
    """Persist the user's edits — human in the loop is the rule; their text is the final text."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    d = db.get(Document, doc_id)
    if d is None or d.user_id != u.id:
        ui = current_lang(request)
        return page(f"<div class='card'>{escape(t('app.not_found', ui))}</div>", u,
                    lang=ui, switch_urls=SWITCH_URLS)
    d.content = content
    db.commit()
    return redirect(f"/documents/{d.id}?saved=1")


@router.get("/documents/{doc_id}/print", response_class=HTMLResponse)
def document_print(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Standalone A4 print view (Lovable-designed template) — the browser's print dialog saves
    it as a styled PDF. At deploy time the same template gets a server-side .pdf renderer."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    d = db.get(Document, doc_id)
    if d is None or d.user_id != u.id:
        ui = current_lang(request)
        return page(f"<div class='card'>{escape(t('app.not_found', ui))}</div>", u,
                    lang=ui, switch_urls=SWITCH_URLS)
    post = db.get(Posting, d.posting_id) if d.posting_id else None
    role = f"{post.title} — {post.company}" if post else ""
    name = u.name or u.email.split("@")[0]
    titles = _KIND_TITLE.get(d.lang, _KIND_TITLE["en"])
    footer_word = "Генерирано с" if d.lang == "bg" else "Generated with"
    return render_document_html(
        title=titles.get(d.kind, d.kind), name=name, role=role,
        content=d.content, lang=d.lang,
        footer=f"{footer_word} Job Agent — {d.created_at:%d %B %Y}")
