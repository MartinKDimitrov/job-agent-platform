"""Shared web layer: the HTML shell and per-request user/session helpers.

One-page app design (Lovable project 038dd6c8): styles live in /static/design.css; the shell
carries the header (brand mark, language switch, user dropdown menu) and the inline SVG icon
symbols used across pages. Every router imports from here so layout stays in one place.
"""
import hashlib
from html import escape  # re-exported so routers import escape from one place
from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..data.models import User
from ..data.security import read_token
from .seo import meta_tags
from .i18n import t, LANGS, DEFAULT_LANG
from .translations import LANG_NAMES
from ..data.activity_repo import touch

__all__ = ["escape", "page", "current_user", "redirect", "icon"]


# Cache-busting version for the stylesheet: content hash computed at import time, so browsers
# refetch design.css the moment it changes (a stale cached copy left pages unstyled once).
_CSS_PATH = Path(__file__).parent / "static" / "design.css"
try:
    _CSS_VERSION = hashlib.sha256(_CSS_PATH.read_bytes()).hexdigest()[:10]
except OSError:
    _CSS_VERSION = "0"


def current_user(request: Request, db: Session) -> User | None:
    tok = request.cookies.get("token")
    if not tok:
        return None
    uid = read_token(tok)
    if not uid:
        return None
    u = db.get(User, uid)
    if u:
        touch(db, u.id)          # record activity (throttled) — drives the daily job's "active" gate
    return u


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def icon(name: str, cls: str = "icon") -> str:
    """Inline SVG icon by symbol id (defs are embedded once in the shell)."""
    return f"<svg class='{cls}' aria-hidden='true'><use href='#i-{name}'/></svg>"


# Inline SVG symbol definitions (1.75px stroke line icons + the brand mark), embedded once per
# page — offline-safe, no icon fonts/CDNs.
_SVG_DEFS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></symbol>
<symbol id="i-building" viewBox="0 0 24 24"><path d="M4 21V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v16"/><path d="M3 21h18"/><path d="M9 8h.01M9 12h.01M9 16h.01M14 8h.01M14 12h.01M14 16h.01"/></symbol>
<symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/></symbol>
<symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21s-7-7.5-7-12a7 7 0 1 1 14 0c0 4.5-7 12-7 12z"/><circle cx="12" cy="10" r="2.5"/></symbol>
<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
<symbol id="i-doc" viewBox="0 0 24 24"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></symbol>
<symbol id="i-mail" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></symbol>
<symbol id="i-plane" viewBox="0 0 24 24"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></symbol>
<symbol id="i-key" viewBox="0 0 24 24"><circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 10.2-10.2M17 6l3 3M14 9l3 3"/></symbol>
<symbol id="i-download" viewBox="0 0 24 24"><path d="M12 3v13"/><path d="m7 12 5 5 5-5"/><path d="M4 21h16"/></symbol>
<symbol id="i-warning" viewBox="0 0 24 24"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5"/><path d="M12 18h.01"/></symbol>
<symbol id="i-pause" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><path d="M7 4v16l13-8z"/></symbol>
<symbol id="i-logout" viewBox="0 0 24 24"><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5"/><path d="M5 12h11"/></symbol>
<symbol id="i-edit" viewBox="0 0 24 24"><path d="M17 3a2.8 2.8 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5z"/></symbol>
<symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></symbol>
<symbol id="i-logo" viewBox="0 0 32 32"><rect x="2" y="2" width="28" height="28" rx="8" fill="var(--green)"/><path d="M16 8 L23 16 L16 24 L9 16 Z" fill="#fff"/></symbol>
<symbol id="i-theme" viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></symbol>
</defs></svg>"""


def _usermenu(user: User, lang: str, paused: bool | None) -> str:
    """The account dropdown (details/summary — no JS). Account actions live here, not on a
    separate screen (one-page design)."""
    pause_item = ""
    if paused is False:
        pause_item = (
            "<form method='post' action='/account/found-job' style='margin:0'>"
            "<input type='hidden' name='value' value='1'>"
            f"<button type='submit'>{icon('pause', 'icon sm')}"
            f"🎉 {escape(t('menu.pause', lang))}</button></form><div class='sep'></div>")
    elif paused is True:
        pause_item = (
            "<form method='post' action='/account/found-job' style='margin:0'>"
            "<input type='hidden' name='value' value='0'>"
            f"<button type='submit'>{icon('play', 'icon sm')}"
            f"{escape(t('menu.resume', lang))}</button></form><div class='sep'></div>")
    name = user.name or user.email.split("@")[0]
    return f"""<details class='usermenu'><summary>{escape(name)}</summary><div class='menu'>
<a href='/onboarding'><b>＋</b>&nbsp;{escape(t('form.new_profile', lang))}</a>
<div class='sep'></div>
{pause_item}<a href='/documents'>{icon('doc', 'icon sm')}{escape(t('nav.documents', lang))}</a>
<a href='/account'>{icon('key', 'icon sm')}{escape(t('menu.settings', lang))}</a>
<a href='/account/export'>{icon('download', 'icon sm')}{escape(t('menu.export', lang))}</a>
<a href='/sources'>{icon('search', 'icon sm')}{escape(t('nav.sources', lang))}</a>
<div class='sep'></div>
<a href='/account#delete' class='danger'>{icon('warning', 'icon sm')}{escape(t('menu.delete', lang))}</a>
<a href='/logout'>{icon('logout', 'icon sm')}{escape(t('nav.logout', lang))}</a>
</div></details>"""


def page(body: str, user: User | None = None, *, title: str = "Job Agent",
         description: str = "", path: str = "/", noindex: bool = True,
         head_extra: str = "", lang: str = DEFAULT_LANG,
         switch_urls: dict[str, str] | None = None,
         hreflang: list[tuple[str, str]] | None = None,
         paused: bool | None = None, full_bleed: bool = False) -> str:
    """Render the page shell.

    `noindex` defaults to True so private pages never leak into search by accident — public
    pages opt in with noindex=False and a real description. `head_extra` is extra <head> content
    (e.g. JSON-LD). `lang` sets <html lang> and localises the chrome. `switch_urls` renders the
    language switcher (public pages). `hreflang` renders alternate-language links. `paused`
    (when known) enables the direct pause/resume item in the user menu."""
    switcher = ""
    if switch_urls:
        # 13 languages don't fit as a link row — a native <select> that navigates on change
        # (progressive: it's a plain dropdown, no framework; each option carries its URL).
        opts = []
        for code in LANGS:
            url = switch_urls.get(code, f"/lang/{code}")
            sel = " selected" if code == lang else ""
            opts.append(f"<option value='{escape(url)}'{sel}>"
                        f"{escape(LANG_NAMES.get(code, code.upper()))}</option>")
        switcher = ("<select class='langsw' aria-label='Language' "
                    "onchange=\"location.href=this.value\">" + "".join(opts) + "</select>")
    if user:
        right = f"{switcher}{_usermenu(user, lang, paused)}"
    else:
        right = (f"{switcher}<a class='btn gray small' href='/login'>{escape(t('nav.login', lang))}</a>"
                 f"<a class='btn small' href='/register'>{escape(t('nav.register', lang))}</a>")
    seo = meta_tags(title, description, path, noindex=noindex)
    hl = "\n".join(
        f'<link rel="alternate" hreflang="{escape(code)}" href="{escape(url)}">'
        for code, url in (hreflang or []))
    content = body if full_bleed else f'<main class="wrap">{body}</main>'
    loading_msg = t("app.loading", lang)
    return f"""<!doctype html><html lang="{escape(lang)}"><head><meta charset="utf-8">
<script>(function(){{try{{var t=localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');document.documentElement.dataset.theme=t;}}catch(e){{}}}})();
function __toggleTheme(){{var d=document.documentElement,n=d.dataset.theme==='dark'?'light':'dark';d.dataset.theme=n;try{{localStorage.setItem('theme',n)}}catch(e){{}}}}</script>
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
{seo}
{hl}
{head_extra}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap">
<link rel="stylesheet" href="/static/design.css?v={_CSS_VERSION}">
</head><body>
{_SVG_DEFS}
<header><span class="brand"><a href="/">{icon('logo', 'logo')}Job Agent</a></span>
<span class="right"><button type="button" class="theme-toggle" onclick="__toggleTheme()" aria-label="Тема" title="Светла / тъмна тема">{icon('theme', 'icon')}</button>{right}</span></header>
{content}
<footer class="site">Job Agent</footer>
<div id="loading-overlay" role="status" aria-live="polite">
<div class="spinner"></div><div class="msg">{loading_msg}</div></div>
<script>
(function () {{
  // Ripple on buttons/tabs — pure visual, never blocks the click.
  document.addEventListener("pointerdown", function (e) {{
    var el = e.target.closest(".btn, .profile-tabs .tab");
    if (!el) return;
    var rect = el.getBoundingClientRect();
    var d = Math.max(rect.width, rect.height);
    var r = document.createElement("span");
    r.className = "ripple";
    r.style.width = r.style.height = d + "px";
    r.style.left = (e.clientX - rect.left - d / 2) + "px";
    r.style.top = (e.clientY - rect.top - d / 2) + "px";
    el.appendChild(r);
    setTimeout(function () {{ r.remove(); }}, 500);
  }});

  // Full-screen loading overlay for server round-trips: every same-tab form submit,
  // plus profile-tab navigation (they trigger a fresh server fetch).
  var overlay = document.getElementById("loading-overlay");
  function show() {{ overlay.classList.add("show"); }}
  document.addEventListener("submit", function (e) {{
    var f = e.target;
    if (f.target === "_blank" || f.hasAttribute("data-no-overlay")) return;
    if (e.defaultPrevented) return;
    show();
  }}, true);
  document.addEventListener("click", function (e) {{
    var a = e.target.closest(".profile-tabs .tab[href]");
    if (a && a.target !== "_blank" && !e.metaKey && !e.ctrlKey) show();
  }});
  // Back/forward restores from bfcache with the overlay still up — always hide on show.
  window.addEventListener("pageshow", function () {{ overlay.classList.remove("show"); }});
}})();
</script></body></html>"""
