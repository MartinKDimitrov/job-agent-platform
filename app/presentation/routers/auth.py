"""Landing/dashboard + email-password auth + Google OAuth."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import User, Profile
from ...data.security import hash_password, verify_password, make_token
from ...core.config import settings
from ..web import page, current_user, redirect, escape
from ..seo import site_jsonld, abs_url
from ..i18n import t, current_lang, LANGS

router = APIRouter()


def _login_response(user_id: int):
    """Redirect home with the auth cookie set — shared by register/login/oauth."""
    resp = redirect("/")
    resp.set_cookie("token", make_token(user_id), httponly=True, samesite="lax")
    return resp


def _landing(lang: str, path: str) -> str:
    """Public, indexable landing in the given language, with hreflang + site JSON-LD."""
    body = (f"<div class='card'><h2>{escape(t('landing.h1', lang))}</h2>"
            f"<p class='small'>{escape(t('landing.sub', lang))}</p>"
            f"<a class='btn' href='/register'>{escape(t('landing.get_started', lang))}</a> "
            f"<a class='btn gray' href='/login'>{escape(t('landing.login', lang))}</a></div>")
    hreflang = [("en", abs_url("/")), ("bg", abs_url("/bg")), ("x-default", abs_url("/"))]
    return page(body, title=t("landing.title", lang), description=t("landing.description", lang),
                path=path, noindex=False, head_extra=site_jsonld(), lang=lang,
                switch_urls={"en": "/", "bg": "/bg"}, hreflang=hreflang)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return _landing("en", "/")
    profiles = db.execute(select(Profile).where(Profile.user_id == u.id)
                          .order_by(Profile.created_at)).scalars().all()
    if not profiles:
        # brand-new user: the empty state IS the onboarding — no navigation (one-page design)
        from .onboarding import onboarding_card
        body = ("<div class='page-head'><div class='title-block'><h1>Welcome 👋</h1>"
                "<p class='sub'>No profiles yet — create your first search profile in about "
                "30 seconds.</p></div></div>" + onboarding_card())
        return page(body, u, title="Get started — Job Agent")
    # one-page app: first profile active (tabs switch via /profiles/{id})
    from .profiles import render_app
    return render_app(db, u, profiles[0], profiles, lang=current_lang(request))


@router.get("/bg", response_class=HTMLResponse)
def home_bg(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return redirect("/")            # logged-in users go to their dashboard
    return _landing("bg", "/bg")


@router.get("/lang/{code}")
def set_lang(code: str, request: Request):
    """Set the UI language cookie and return to where the user was (same-site only)."""
    base = settings.site_url.rstrip("/")
    ref = request.headers.get("referer") or "/"
    target = ref if (ref.startswith(base) or ref.startswith("/")) else "/"
    resp = redirect(target)
    if code in LANGS:
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    lang = current_lang(request)
    body = (f"<div class='card'><h2>{escape(t('register.heading', lang))}</h2>"
            "<form method='post' action='/register'>"
            f"<label>{escape(t('register.name', lang))}</label><input name='name'>"
            f"<label>{escape(t('register.email', lang))}</label><input name='email' type='email' required>"
            f"<label>{escape(t('register.password', lang))}</label><input name='password' type='password' required>"
            f"<p style='margin-top:12px'><button class='btn'>{escape(t('register.submit', lang))}</button></p></form>"
            f"<p class='small'>{escape(t('login.or', lang))} <a href='/auth/google'>{escape(t('auth.google', lang))}</a></p></div>")
    return page(body, title=t("register.title", lang), lang=lang,
                switch_urls={"en": "/lang/en", "bg": "/lang/bg"})


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
def login_form(request: Request, oauth_err: str | None = None):
    lang = current_lang(request)
    err = ""
    if oauth_err:
        err = ("<div class='card' style='border-color:#c0392b;background:#fdecea'>"
               "Google sign-in didn't complete (the session expired or the page was stale). "
               "Please try again.</div>")
    body = (f"{err}<div class='card'><h2>{escape(t('login.heading', lang))}</h2>"
            "<form method='post' action='/login'>"
            f"<label>{escape(t('login.email', lang))}</label><input name='email' type='email' required>"
            f"<label>{escape(t('login.password', lang))}</label><input name='password' type='password' required>"
            f"<p style='margin-top:12px'><button class='btn'>{escape(t('login.submit', lang))}</button></p></form>"
            f"<p class='small'>{escape(t('login.or', lang))} <a href='/auth/google'>{escape(t('auth.google', lang))}</a></p></div>")
    return page(body, title=t("login.title", lang), lang=lang,
                switch_urls={"en": "/lang/en", "bg": "/lang/bg"})


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
    # Canonicalize the host BEFORE starting the flow: the state lives in a session cookie, and
    # a cookie set on 127.0.0.1 is not sent to localhost (and vice versa) — starting on one host
    # and returning on the redirect-URI host guarantees a MismatchingStateError. So if the user
    # opened the app on a non-canonical host, bounce them to the canonical one first.
    from urllib.parse import urlparse
    canonical = urlparse(settings.oauth_redirect_base).netloc
    if canonical and request.url.netloc != canonical:
        return redirect(f"{settings.oauth_redirect_base}/auth/google")
    redirect_uri = settings.oauth_redirect_base + "/auth/google/callback"
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def auth_google_cb(request: Request, db: Session = Depends(get_db)):
    if not _oauth:
        return redirect("/login")
    try:
        token = await _oauth.google.authorize_access_token(request)
    except Exception:  # noqa: BLE001 — stale state / expired session / user retried: not a 500
        return redirect("/login?oauth_err=1")
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not email:
        return redirect("/login")
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not u:
        u = User(email=email, name=info.get("name", ""), google_sub=info.get("sub"))
        db.add(u); db.commit(); db.refresh(u)
    return _login_response(u.id)
