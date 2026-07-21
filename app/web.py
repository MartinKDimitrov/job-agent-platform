"""Shared web layer: the HTML shell and per-request user/session helpers.

Every router imports from here so the layout and auth-cookie handling live in one place.
Keeping this small is deliberate — feature routers stay focused on their own concern.
"""
from html import escape  # re-exported so routers import escape from one place

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .models import User
from .security import read_token
from .seo import meta_tags
from .i18n import t, LANGS, DEFAULT_LANG

__all__ = ["escape", "page", "current_user", "redirect"]


def current_user(request: Request, db: Session) -> User | None:
    tok = request.cookies.get("token")
    if not tok:
        return None
    uid = read_token(tok)
    if not uid:
        return None
    return db.get(User, uid)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def page(body: str, user: User | None = None, *, title: str = "Job Agent",
         description: str = "", path: str = "/", noindex: bool = True,
         head_extra: str = "", lang: str = DEFAULT_LANG,
         switch_urls: dict[str, str] | None = None,
         hreflang: list[tuple[str, str]] | None = None) -> str:
    """Render the page shell.

    `noindex` defaults to True so private pages never leak into search by accident — public
    pages opt in with noindex=False and a real description. `head_extra` is extra <head> content
    (e.g. JSON-LD). `lang` sets <html lang> and localises the nav. `switch_urls` (per-language
    target URLs) renders a language switcher — only public pages pass it. `hreflang` renders
    alternate-language <link>s for the public, language-prefixed pages."""
    if user:
        nav = (f"<a href='/'>{escape(t('nav.dashboard', lang))}</a>"
               f"<a href='/sources'>{escape(t('nav.sources', lang))}</a>"
               f"<a href='/account'>{escape(t('nav.account', lang))}</a>"
               f"<a href='/logout'>{escape(t('nav.logout', lang))}</a>")
    else:
        nav = (f"<a href='/login'>{escape(t('nav.login', lang))}</a>"
               f"<a href='/register'>{escape(t('nav.register', lang))}</a>")
    who = f"<span class='who'>{escape(user.email)}</span>" if user else ""
    switcher = ""
    if switch_urls:
        parts = []
        for code in LANGS:
            url = switch_urls.get(code, f"/lang/{code}")
            active = " style='font-weight:700;color:#fff'" if code == lang else ""
            parts.append(f"<a href='{escape(url)}'{active}>{code.upper()}</a>")
        switcher = "<span class='langsw'>" + " · ".join(parts) + "</span>"
    seo = meta_tags(title, description, path, noindex=noindex)
    hl = "\n".join(
        f'<link rel="alternate" hreflang="{escape(code)}" href="{escape(url)}">'
        for code, url in (hreflang or []))
    return f"""<!doctype html><html lang="{escape(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
{seo}
{hl}
{head_extra}
<style>
*{{box-sizing:border-box}} body{{font-family:Arial,Helvetica,sans-serif;margin:0;background:#f5f6fa;color:#222}}
header{{background:#1f3864;color:#fff;padding:12px 22px;display:flex;gap:16px;align-items:center}}
header b{{font-size:16px}} header a{{color:#cfe0ff;text-decoration:none;font-size:14px}}
.who{{font-size:12px;color:#9fb4dd}}
.right{{margin-left:auto;display:flex;gap:12px;align-items:center}}
.langsw a{{font-size:12px}}
.wrap{{padding:20px 22px;max-width:1000px;margin:0 auto}}
.card{{background:#fff;border:1px solid #e3e6ee;border-radius:8px;padding:16px 18px;margin-bottom:14px}}
label{{display:block;font-size:12px;color:#555;margin:8px 0 3px}} input,select,textarea{{width:100%;padding:8px;border:1px solid #c8ccd8;border-radius:6px;font-size:14px}}
.btn{{background:#2e5496;color:#fff;border:0;padding:9px 14px;border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block;font-size:14px}}
.btn.green{{background:#2e7d32}} .btn.gray{{background:#8a94a6}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:8px;border-bottom:1px solid #eef0f5;font-size:13px;text-align:left;vertical-align:top}} th{{background:#1f3864;color:#fff}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#c6e0b4}}
.chip{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;margin:2px 3px 2px 0;line-height:1.5}}
.tuner{{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}}
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
<header><b>🧭 Job Agent</b>{nav}<span class='right'>{who}{switcher}</span></header>
<div class="wrap">{body}</div></body></html>"""
