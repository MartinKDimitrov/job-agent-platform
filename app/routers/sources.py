"""Sources screen: the built-in platforms we cover + user-added sources."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Source
from ..web import page, current_user, redirect, escape

router = APIRouter()


@router.get("/sources", response_class=HTMLResponse)
def sources_view(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    builtin = db.execute(select(Source).where(Source.user_id.is_(None))).scalars().all()
    mine = db.execute(select(Source).where(Source.user_id == u.id)).scalars().all()

    def tbl(items, own):
        r = ""
        for s in items:
            r += (f"<tr><td>{escape(s.name)}</td><td class='small'>{escape(s.kind)}</td>"
                  f"<td class='small'>{escape(s.url)}</td></tr>")
        return r or f"<tr><td colspan='3' class='small'>{'None yet.' if own else '—'}</td></tr>"

    body = f"""<div class='card'><h2>Where we search</h2>
    <p class='small'>Built-in platforms we cover:</p>
    <table><tr><th>Source</th><th>Type</th><th>Endpoint</th></tr>{tbl(builtin, False)}</table></div>
    <div class='card'><h3>Your added sources</h3>
    <table><tr><th>Source</th><th>Type</th><th>URL</th></tr>{tbl(mine, True)}</table>
    <h4 style='margin-top:14px'>Add a platform we don't have</h4>
    <form method='post' action='/sources'>
      <div class='row2'><div><label>Name</label><input name='name' required></div>
      <div><label>URL</label><input name='url' placeholder='https://...' required></div></div>
      <p style='margin-top:10px'><button class='btn'>Add source</button></p></form>
    <p class='small'>We'll try to crawl it with our adapters; if not possible it stays as a manual link.</p>
    </div>"""
    return page(body, u)


@router.post("/sources")
def add_source(request: Request, name: str = Form(...), url: str = Form(...),
               db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    db.add(Source(user_id=u.id, name=name, url=url, kind="manual", enabled=True))
    db.commit()
    return redirect("/sources")
