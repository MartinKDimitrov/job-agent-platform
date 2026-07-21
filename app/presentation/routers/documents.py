"""Generated documents: create (CV / cover letter for a match), view, list. Owner-checked."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Document, Posting, Match, Profile
from ...application.usecases.generate_document import generate_document, GenerationError
from ..web import page, current_user, redirect, escape
from ..doc_template import render_document_html

router = APIRouter()

_KIND_LABEL = {"cv": "CV", "cover_letter": "Cover letter"}
_KIND_TITLE = {"cv": "Curriculum Vitae", "cover_letter": "Cover Letter"}


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
    except GenerationError as e:
        return redirect(f"/profiles/{pid}?gen_err={str(e)[:180]}")
    return redirect(f"/documents/{doc.id}")


@router.get("/documents", response_class=HTMLResponse)
def documents_list(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    docs = db.execute(select(Document, Posting)
                      .outerjoin(Posting, Document.posting_id == Posting.id)
                      .where(Document.user_id == u.id)
                      .order_by(Document.created_at.desc())).all()
    rows = "".join(
        f"<tr><td><a href='/documents/{d.id}'>{_KIND_LABEL.get(d.kind, d.kind)} "
        f"({escape(d.lang.upper())})</a></td>"
        f"<td>{escape(p.title if p else '(posting removed)')}"
        f"<br><span class='small'>{escape(p.company if p else '')}</span></td>"
        f"<td class='small'>{d.created_at:%Y-%m-%d %H:%M}</td></tr>"
        for d, p in docs
    ) or "<tr><td colspan='3' class='small'>No documents yet — generate one from a match.</td></tr>"
    body = (f"<div class='card'><h2>My documents</h2>"
            f"<table><tr><th>Document</th><th>Job</th><th>Created</th></tr>{rows}</table></div>")
    return page(body, u, title="My documents — Job Agent")


@router.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_view(doc_id: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    d = db.get(Document, doc_id)
    if d is None or d.user_id != u.id:
        return page("<div class='card'>Not found.</div>", u)
    post = db.get(Posting, d.posting_id) if d.posting_id else None
    job = (f"{escape(post.title)} — {escape(post.company)}" if post else "(posting removed)")
    apply_btn = (f"<a class='btn green' href='{escape(post.apply_url or post.url)}' "
                 f"target='_blank'>Apply</a>" if post and (post.apply_url or post.url) else "")
    # regenerate controls: resolve the profile via the Match table (documents don't store it)
    regen = ""
    prof = _profile_for(db, u.id, d.posting_id)
    if prof and post:
        other_lang = "bg" if d.lang == "en" else "en"
        other_kind = "cover_letter" if d.kind == "cv" else "cv"
        busy = ("onsubmit=\"var b=this.querySelector('button');"
                "setTimeout(function(){b.disabled=true;b.textContent='⏳ Generating…';},0);\"")
        regen = (
            f"<form method='post' action='/profiles/{prof.id}/postings/{post.id}/generate' style='display:inline' {busy}>"
            f"<input type='hidden' name='kind' value='{escape(d.kind)}'>"
            f"<input type='hidden' name='lang' value='{other_lang}'>"
            f"<button class='btn gray'>Regenerate in {other_lang.upper()}</button></form> "
            f"<form method='post' action='/profiles/{prof.id}/postings/{post.id}/generate' style='display:inline' {busy}>"
            f"<input type='hidden' name='kind' value='{other_kind}'>"
            f"<input type='hidden' name='lang' value='{escape(d.lang)}'>"
            f"<button class='btn gray'>{_KIND_LABEL[other_kind]} for this job</button></form>")
    body = f"""<div class='card'>
    <h2>{_KIND_LABEL.get(d.kind, d.kind)} <span class='small'>· {escape(d.lang.upper())} ·
    {escape(d.provider)}/{escape(d.model)} · prompt {escape(d.prompt_version)}</span></h2>
    <p class='small'>For: {job}</p>
    <p class='small'><b>Review and edit before using</b> — AI output is a draft, you own the
    final text.</p>
    <textarea rows='24' style='font-family:Georgia,serif' readonly>{escape(d.content)}</textarea>
    <p style='margin-top:12px'>
    <a class='btn' href='/documents/{d.id}/print' target='_blank'>⬇ Download PDF</a>
    {apply_btn} {regen}
    <a class='btn gray' href='/documents'>My documents</a></p></div>"""
    return page(body, u, title=f"{_KIND_LABEL.get(d.kind, d.kind)} — Job Agent")


@router.get("/documents/{doc_id}/print", response_class=HTMLResponse)
def document_print(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Standalone A4 print view (Lovable-designed template) — the browser's print dialog saves
    it as a styled PDF. At deploy time the same template gets a server-side .pdf renderer."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    d = db.get(Document, doc_id)
    if d is None or d.user_id != u.id:
        return page("<div class='card'>Not found.</div>", u)
    post = db.get(Posting, d.posting_id) if d.posting_id else None
    role = f"{post.title} — {post.company}" if post else ""
    name = u.name or u.email.split("@")[0]
    return render_document_html(
        title=_KIND_TITLE.get(d.kind, d.kind), name=name, role=role,
        content=d.content, lang=d.lang,
        footer=f"Generated with Job Agent — {d.created_at:%d %B %Y}")
