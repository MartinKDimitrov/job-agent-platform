import hashlib
from html import escape

from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db, init_db
from .models import User, Profile, Source, Posting, Match
from .security import hash_password, verify_password, make_token, read_token
from .scoring import score
from .config import settings

app = FastAPI(title="Job Agent Platform")

# Session cookie is required by Authlib's OAuth flow (stores the state param).
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")


@app.on_event("startup")
def _startup():
    init_db()


# ---------- auth helpers ----------
def current_user(request: Request, db: Session) -> User | None:
    tok = request.cookies.get("token")
    if not tok:
        return None
    uid = read_token(tok)
    if not uid:
        return None
    return db.get(User, uid)


def _redirect(url: str):
    return RedirectResponse(url, status_code=303)


# ---------- HTML shell ----------
def page(body: str, user: User | None = None, title="Job Agent") -> str:
    nav = ("<a href='/'>Dashboard</a><a href='/sources'>Sources</a>"
           "<a href='/logout'>Logout</a>") if user else \
          ("<a href='/login'>Login</a><a href='/register'>Register</a>")
    who = f"<span class='who'>{escape(user.email)}</span>" if user else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
<style>
*{{box-sizing:border-box}} body{{font-family:Arial,Helvetica,sans-serif;margin:0;background:#f5f6fa;color:#222}}
header{{background:#1f3864;color:#fff;padding:12px 22px;display:flex;gap:16px;align-items:center}}
header b{{font-size:16px}} header a{{color:#cfe0ff;text-decoration:none;font-size:14px}}
.who{{margin-left:auto;font-size:12px;color:#9fb4dd}}
.wrap{{padding:20px 22px;max-width:1000px;margin:0 auto}}
.card{{background:#fff;border:1px solid #e3e6ee;border-radius:8px;padding:16px 18px;margin-bottom:14px}}
label{{display:block;font-size:12px;color:#555;margin:8px 0 3px}} input,select,textarea{{width:100%;padding:8px;border:1px solid #c8ccd8;border-radius:6px;font-size:14px}}
.btn{{background:#2e5496;color:#fff;border:0;padding:9px 14px;border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block;font-size:14px}}
.btn.green{{background:#2e7d32}} .btn.gray{{background:#8a94a6}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:8px;border-bottom:1px solid #eef0f5;font-size:13px;text-align:left;vertical-align:top}} th{{background:#1f3864;color:#fff}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#c6e0b4}}
.small{{color:#777;font-size:12px}} .row2{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
/* --- mobile-friendly: stack the layout and turn table rows into cards --- */
@media (max-width:700px){{
  header{{flex-wrap:wrap;gap:10px;padding:10px 14px}}
  .who{{margin-left:0;width:100%}}
  .wrap{{padding:14px}}
  .row2{{grid-template-columns:1fr}}
  .card{{padding:14px}}
  table{{background:transparent}}
  thead{{display:none}}
  table,tbody,tr,td{{display:block;width:100%}}
  tr{{background:#fff;border:1px solid #e3e6ee;border-radius:8px;margin-bottom:10px;padding:6px 4px}}
  td{{border:0;border-bottom:1px solid #f1f3f8;padding:8px 10px}}
  td:last-child{{border-bottom:0}}
  .btn{{width:100%;text-align:center}}
  input,select,textarea{{font-size:16px}} /* prevents iOS zoom-on-focus */
}}
</style></head><body>
<header><b>🧭 Job Agent</b>{nav}{who}</header>
<div class="wrap">{body}</div></body></html>"""


# ---------- landing / auth ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        body = ("<div class='card'><h2>Find jobs that match you</h2>"
                "<p class='small'>Create profiles, score openings against them, and apply directly.</p>"
                "<a class='btn' href='/register'>Get started</a> "
                "<a class='btn gray' href='/login'>Login</a></div>")
        return page(body)
    profiles = db.execute(select(Profile).where(Profile.user_id == u.id)).scalars().all()
    rows = "".join(
        f"<tr><td><a href='/profiles/{p.id}'>{escape(p.name)}</a></td>"
        f"<td class='small'>{escape(p.target_roles)}</td>"
        f"<td>{p.min_match}%</td></tr>" for p in profiles
    ) or "<tr><td colspan='3' class='small'>No profiles yet.</td></tr>"
    body = (f"<div class='card'><h2>Your search profiles</h2>"
            f"<table><tr><th>Profile</th><th>Target roles</th><th>Min match</th></tr>{rows}</table>"
            f"<p style='margin-top:12px'><a class='btn' href='/profiles/new'>+ New profile</a></p></div>")
    return page(body, u)


@app.get("/register", response_class=HTMLResponse)
def register_form():
    body = ("<div class='card'><h2>Register</h2><form method='post' action='/register'>"
            "<label>Name</label><input name='name'>"
            "<label>Email</label><input name='email' type='email' required>"
            "<label>Password</label><input name='password' type='password' required>"
            "<p style='margin-top:12px'><button class='btn'>Create account</button></p></form>"
            "<p class='small'>Or <a href='/auth/google'>Sign in with Google</a></p></div>")
    return page(body)


@app.post("/register")
def register(email: str = Form(...), password: str = Form(...), name: str = Form(""),
             db: Session = Depends(get_db)):
    email = email.strip().lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        return page("<div class='card'>Email already registered. <a href='/login'>Login</a></div>")
    u = User(email=email, password_hash=hash_password(password), name=name)
    db.add(u); db.commit(); db.refresh(u)
    resp = _redirect("/")
    resp.set_cookie("token", make_token(u.id), httponly=True, samesite="lax")
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_form():
    body = ("<div class='card'><h2>Login</h2><form method='post' action='/login'>"
            "<label>Email</label><input name='email' type='email' required>"
            "<label>Password</label><input name='password' type='password' required>"
            "<p style='margin-top:12px'><button class='btn'>Login</button></p></form>"
            "<p class='small'>Or <a href='/auth/google'>Sign in with Google</a></p></div>")
    return page(body)


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not u or not u.password_hash or not verify_password(password, u.password_hash):
        return page("<div class='card'>Invalid credentials. <a href='/login'>Try again</a></div>")
    resp = _redirect("/")
    resp.set_cookie("token", make_token(u.id), httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = _redirect("/")
    resp.delete_cookie("token")
    return resp


# ---------- Google OAuth (optional; guarded if unconfigured) ----------
_oauth = None
if settings.google_client_id and settings.google_client_secret:
    from authlib.integrations.starlette_client import OAuth
    _oauth = OAuth()
    _oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@app.get("/auth/google")
async def auth_google(request: Request):
    if not _oauth:
        return page("<div class='card'>Google login is not configured yet "
                    "(set GOOGLE_CLIENT_ID / SECRET in .env). Use email + password.</div>")
    redirect_uri = settings.oauth_redirect_base + "/auth/google/callback"
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback")
async def auth_google_cb(request: Request, db: Session = Depends(get_db)):
    if not _oauth:
        return _redirect("/login")
    token = await _oauth.google.authorize_access_token(request)
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not email:
        return _redirect("/login")
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not u:
        u = User(email=email, name=info.get("name", ""), google_sub=info.get("sub"))
        db.add(u); db.commit(); db.refresh(u)
    resp = _redirect("/")
    resp.set_cookie("token", make_token(u.id), httponly=True, samesite="lax")
    return resp


# ---------- profiles ----------
@app.get("/profiles/new", response_class=HTMLResponse)
def profile_new(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return _redirect("/login")
    body = """<div class='card'><h2>New profile</h2><form method='post' action='/profiles'>
    <label>Profile name (e.g. "Senior Android")</label><input name='name' required>
    <label>Target roles (comma-separated)</label><input name='target_roles'>
    <label>Skills (comma-separated)</label><textarea name='skills' rows='3'></textarea>
    <label>Experience (short)</label><textarea name='experience' rows='3'></textarea>
    <div class='row2'>
      <div><label>Languages</label><input name='languages' value='Bulgarian, English'></div>
      <div><label>English level (CEFR)</label>
        <select name='english_level'><option>A2</option><option>B1</option>
        <option selected>B2</option><option>C1</option><option>C2</option></select></div>
    </div>
    <div class='row2'>
      <div><label>Location preference</label><input name='location_pref' value='Remote / Varna'></div>
      <div><label>Remote preference</label>
        <select name='remote_pref'><option selected>remote</option><option>hybrid</option>
        <option>onsite</option><option>any</option></select></div>
    </div>
    <div class='row2'>
      <div><label>Salary expectation</label><input name='salary_expectation'></div>
      <div><label>Min match %</label><input name='min_match' type='number' value='65' min='0' max='100'></div>
    </div>
    <p style='margin-top:12px'><button class='btn'>Create</button>
    <a class='btn gray' href='/'>Cancel</a></p></form></div>"""
    return page(body, u)


@app.post("/profiles")
def profile_create(request: Request, name: str = Form(...), target_roles: str = Form(""),
                   skills: str = Form(""), experience: str = Form(""),
                   languages: str = Form(""), english_level: str = Form("B2"),
                   location_pref: str = Form(""), remote_pref: str = Form("remote"),
                   salary_expectation: str = Form(""), min_match: int = Form(65),
                   db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return _redirect("/login")
    p = Profile(user_id=u.id, name=name, target_roles=target_roles, skills=skills,
                experience=experience, languages=languages, english_level=english_level,
                location_pref=location_pref, remote_pref=remote_pref,
                salary_expectation=salary_expectation, min_match=int(min_match))
    db.add(p); db.commit(); db.refresh(p)
    return _redirect(f"/profiles/{p.id}")


@app.get("/profiles/{pid}", response_class=HTMLResponse)
def profile_view(pid: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return _redirect("/login")
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
        miss = ", ".join(m.missing or [])[:80]
        rows += (f"<tr><td>{m.score}%</td>"
                 f"<td><b>{escape(post.title)}</b><br><span class='small'>{escape(post.company)} · {escape(post.location)}</span></td>"
                 f"<td class='small'>{escape(miss)}</td><td>{apply}</td></tr>")
    rows = rows or "<tr><td colspan='4' class='small'>No matches above threshold yet. Add a posting below.</td></tr>"

    body = f"""<div class='card'><h2>{escape(p.name)} <span class='small'>· min {p.min_match}%</span></h2>
    <p class='small'>Target: {escape(p.target_roles)} · {escape(p.remote_pref)} · {escape(p.location_pref)}</p>
    <table><tr><th>Match</th><th>Role / Company</th><th>Missing</th><th></th></tr>{rows}</table></div>
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


@app.post("/profiles/{pid}/postings")
def add_posting(pid: int, request: Request, url: str = Form(""), apply_url: str = Form(""),
                title: str = Form(""), company: str = Form(""), location: str = Form(""),
                description: str = Form(""), db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return _redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return _redirect("/")
    chash = hashlib.sha256((url or title + company + description).encode("utf-8")).hexdigest()[:64]
    post = db.execute(select(Posting).where(Posting.content_hash == chash)).scalar_one_or_none()
    if not post:
        # naive requirement extraction (Phase 1): split JD into bullet-ish lines.
        reqs = [ln.strip("•-*  ").strip() for ln in description.splitlines()
                if len(ln.strip()) > 8][:40]
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
    return _redirect(f"/profiles/{p.id}")


# ---------- sources ----------
@app.get("/sources", response_class=HTMLResponse)
def sources_view(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return _redirect("/login")
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


@app.post("/sources")
def add_source(request: Request, name: str = Form(...), url: str = Form(...),
               db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return _redirect("/login")
    db.add(Source(user_id=u.id, name=name, url=url, kind="manual", enabled=True))
    db.commit()
    return _redirect("/sources")
