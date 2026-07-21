"""Landing/dashboard + email-password auth + Google OAuth."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, Profile
from ..security import hash_password, verify_password, make_token
from ..config import settings
from ..web import page, current_user, redirect, escape
from ..seo import site_jsonld

router = APIRouter()


def _login_response(user_id: int):
    """Redirect home with the auth cookie set — shared by register/login/oauth."""
    resp = redirect("/")
    resp.set_cookie("token", make_token(user_id), httponly=True, samesite="lax")
    return resp


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        body = ("<div class='card'><h2>Find jobs that match you</h2>"
                "<p class='small'>Create profiles, score openings against them, and apply directly.</p>"
                "<a class='btn' href='/register'>Get started</a> "
                "<a class='btn gray' href='/login'>Login</a></div>")
        # The only public, indexable page for now — real title/description + site JSON-LD.
        return page(
            body,
            title="Job Agent — find jobs that match your skills",
            description=("Describe your professional skills and get open positions scored "
                         "against your profile, with a direct apply link for each match."),
            path="/", noindex=False, head_extra=site_jsonld())
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


@router.get("/register", response_class=HTMLResponse)
def register_form():
    body = ("<div class='card'><h2>Register</h2><form method='post' action='/register'>"
            "<label>Name</label><input name='name'>"
            "<label>Email</label><input name='email' type='email' required>"
            "<label>Password</label><input name='password' type='password' required>"
            "<p style='margin-top:12px'><button class='btn'>Create account</button></p></form>"
            "<p class='small'>Or <a href='/auth/google'>Sign in with Google</a></p></div>")
    return page(body)


@router.post("/register")
def register(email: str = Form(...), password: str = Form(...), name: str = Form(""),
             db: Session = Depends(get_db)):
    email = email.strip().lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        return page("<div class='card'>Email already registered. <a href='/login'>Login</a></div>")
    u = User(email=email, password_hash=hash_password(password), name=name)
    db.add(u); db.commit(); db.refresh(u)
    return _login_response(u.id)


@router.get("/login", response_class=HTMLResponse)
def login_form():
    body = ("<div class='card'><h2>Login</h2><form method='post' action='/login'>"
            "<label>Email</label><input name='email' type='email' required>"
            "<label>Password</label><input name='password' type='password' required>"
            "<p style='margin-top:12px'><button class='btn'>Login</button></p></form>"
            "<p class='small'>Or <a href='/auth/google'>Sign in with Google</a></p></div>")
    return page(body)


@router.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not u or not u.password_hash or not verify_password(password, u.password_hash):
        return page("<div class='card'>Invalid credentials. <a href='/login'>Try again</a></div>")
    return _login_response(u.id)


@router.get("/logout")
def logout():
    resp = redirect("/")
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


@router.get("/auth/google")
async def auth_google(request: Request):
    if not _oauth:
        return page("<div class='card'>Google login is not configured yet "
                    "(set GOOGLE_CLIENT_ID / SECRET in .env). Use email + password.</div>")
    redirect_uri = settings.oauth_redirect_base + "/auth/google/callback"
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def auth_google_cb(request: Request, db: Session = Depends(get_db)):
    if not _oauth:
        return redirect("/login")
    token = await _oauth.google.authorize_access_token(request)
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not email:
        return redirect("/login")
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not u:
        u = User(email=email, name=info.get("name", ""), google_sub=info.get("sub"))
        db.add(u); db.commit(); db.refresh(u)
    return _login_response(u.id)
