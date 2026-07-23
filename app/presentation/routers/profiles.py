"""Search profiles: CRUD, validation, the scoring view, and the (Phase-1 scaffold) posting form."""
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Profile, Posting, Match, Document
from ...data.activity_repo import get_activity
from ...domain.scoring import score
from ...domain.extraction import extract_requirements
from ...application.usecases.search import search_db
from ...application.run_stats import RunStats
from ...data.metrics_repo import record_run
from ..web import page, current_user, redirect, escape, icon
from ..i18n import t, current_lang

router = APIRouter()

CEFR_LEVELS = ["A2", "B1", "B2", "C1", "C2"]
REMOTE_PREFS = ["remote", "hybrid", "onsite", "any"]

SWITCH_URLS = {"en": "/lang/en", "bg": "/lang/bg"}   # header language switcher (cookie-based)


# ---------- form + validation (shared by create and edit) ----------
def _err_box(errors: list[str], lang: str) -> str:
    if not errors:
        return ""
    items = "".join(f"<li>{escape(e)}</li>" for e in errors)
    return ("<div class='card' style='border-color:#c0392b;background:#fdecea'>"
            f"<b style='color:#c0392b'>{escape(t('form.fix', lang))}</b>"
            f"<ul style='margin:6px 0 0 18px'>{items}</ul></div>")


def _profile_form(action: str, v: dict, heading: str, errors: list[str] | None = None,
                  lang: str = "en") -> str:
    """Render the profile form prefilled from `v`. Used by both create and edit so the two
    stay in sync and validation can re-render with the user's input preserved."""
    def sel(val, current):
        return " selected" if val == current else ""
    cefr = "".join(f"<option{sel(x, v.get('english_level', 'B2'))}>{x}</option>" for x in CEFR_LEVELS)
    # option VALUES stay English (stored in the DB / validated); labels localise
    remote = "".join(
        f"<option value='{x}'{sel(x, v.get('remote_pref', 'remote'))}>{escape(t(f'opt.{x}', lang))}</option>"
        for x in REMOTE_PREFS)
    return f"""{_err_box(errors or [], lang)}<div class='card'><h2>{escape(heading)}</h2>
    <form method='post' action='{action}'>
    <label>{escape(t('form.name', lang))}</label>
    <input name='name' required maxlength='255' value="{escape(v.get('name', ''))}">
    <label>{escape(t('form.target_roles', lang))}</label>
    <input name='target_roles' value="{escape(v.get('target_roles', ''))}">
    <label>{escape(t('form.skills', lang))}</label>
    <textarea name='skills' rows='3'>{escape(v.get('skills', ''))}</textarea>
    <label>{escape(t('form.experience', lang))}</label>
    <textarea name='experience' rows='3'>{escape(v.get('experience', ''))}</textarea>
    <div class='row2'>
      <div><label>{escape(t('form.languages', lang))}</label>
        <input name='languages' value="{escape(v.get('languages', 'Bulgarian, English'))}"></div>
      <div><label>{escape(t('form.english', lang))}</label><select name='english_level'>{cefr}</select></div>
    </div>
    <div class='row2'>
      <div><label>{escape(t('form.location', lang))}</label>
        <input name='location_pref' value="{escape(v.get('location_pref', 'Remote / Varna'))}"></div>
      <div><label>{escape(t('form.remote', lang))}</label><select name='remote_pref'>{remote}</select></div>
    </div>
    <div class='row2'>
      <div><label>{escape(t('form.country', lang))}</label>
        <input name='country' maxlength='64' value="{escape(v.get('country', 'Bulgaria'))}"></div>
      <div><label style='display:flex;gap:8px;align-items:center;margin-top:28px'>
        <input type='checkbox' name='relocate' value='1'
               {'checked' if v.get('relocate') else ''} style='width:auto'>
        {escape(t('form.relocate', lang))}</label>
        <p class='small'>{escape(t('form.relocate_hint', lang))}</p></div>
    </div>
    <div class='row2'>
      <div><label>{escape(t('form.salary', lang))}</label>
        <input name='salary_expectation' maxlength='64' value="{escape(v.get('salary_expectation', ''))}"></div>
      <div><label>{escape(t('form.min_match', lang))}</label>
        <input name='min_match' type='number' min='0' max='100' value="{escape(str(v.get('min_match', 65)))}"></div>
    </div>
    <p style='margin-top:12px'><button class='btn'>{escape(t('form.save', lang))}</button>
    <a class='btn gray' href='/'>{escape(t('form.cancel', lang))}</a></p></form></div>"""


def _validate_profile(name, min_match, english_level, remote_pref, salary_expectation,
                      lang: str = "en"):
    """Return (errors, clean_name, clean_min_match). Keeps create and edit consistent."""
    errors: list[str] = []
    name = (name or "").strip()
    if not name:
        errors.append(t("err.name_required", lang))
    elif len(name) > 255:
        errors.append(t("err.name_long", lang))
    try:
        mm = int(min_match)
    except (TypeError, ValueError):
        mm = None
    if mm is None or not (0 <= mm <= 100):
        errors.append(t("err.min_match", lang))
        mm = 65
    if english_level not in CEFR_LEVELS:
        errors.append(t("err.english", lang))
    if remote_pref not in REMOTE_PREFS:
        errors.append(t("err.remote", lang))
    if len(salary_expectation or "") > 64:
        errors.append(t("err.salary_long", lang))
    return errors, name, mm


# ---------- score / requirement rendering ----------
def _req_text(r) -> str:
    return r.get("text", "") if isinstance(r, dict) else str(r)


def _req_kind(r) -> str:
    return r.get("kind", "must") if isinstance(r, dict) else "must"


_RING_C = 175.93   # circumference of the r=28 score ring


def _score_ring(sc: float) -> str:
    """Circular progress ring (Lovable design): arc fills to the %, color-coded."""
    pct = max(0, min(100, int(round(sc))))
    cls = "high" if pct >= 65 else ("mid" if pct >= 45 else "low")
    offset = _RING_C * (1 - pct / 100)
    return (f"<div class='score {cls}'><svg viewBox='0 0 64 64' aria-hidden='true'>"
            f"<circle class='track' cx='32' cy='32' r='28' stroke-width='6' fill='none'/>"
            f"<circle class='bar' cx='32' cy='32' r='28' stroke-width='6' fill='none' "
            f"stroke-linecap='round' stroke-dasharray='{_RING_C}' stroke-dashoffset='{offset:.2f}'/>"
            f"</svg><span class='num'>{pct}%</span></div>")


def _gaps_block(covered, missing, lang: str = "en") -> str:
    """Why a posting scored as it did — calm by default (owner feedback: the red chips were too
    intrusive). Collapsed: '✓ N covered · ⚠ N to check'. Click expands a tidy two-column panel
    with the FULL requirement texts (covered vs missing). Transparency on demand."""
    covered = covered or []
    missing = missing or []
    cov_items = [r for r in covered if _req_kind(r) not in ("resp", "soft")]
    must_miss = [r for r in missing if _req_kind(r) == "must"]
    nice_miss = [r for r in missing if _req_kind(r) == "nice"]
    n_missing = len(must_miss) + len(nice_miss)

    chips = ""
    if cov_items:
        chips += f"<span class='chip count'>✓ {len(cov_items)} {escape(t('gaps.covered', lang))}</span>"
    if n_missing:
        chips += f"<span class='chip warn'>⚠ {n_missing} {escape(t('gaps.to_check', lang))}</span>"
    if not chips:
        return ""
    if not n_missing:
        return f"<div class='chips'>{chips}</div>"

    cov_list = "".join(f"<li>{escape(_req_text(r))}</li>" for r in cov_items[:10])
    miss_list = "".join(f"<li>{escape(_req_text(r))}</li>" for r in must_miss)
    nice_list = "".join(f"<li class='nice'>{escape(_req_text(r))}</li>" for r in nice_miss)
    cov_col = (f"<div class='col ok'><h5>✓ {escape(t('gaps.you_cover', lang))}</h5><ul>{cov_list}</ul></div>"
               if cov_list else "")
    must_block = f"<ul>{miss_list}</ul>" if miss_list else ""
    # nice-to-haves get their own subheading so the dimmer bullets are self-explanatory
    nice_block = (f"<h6 class='subhead'>{escape(t('gaps.advantage', lang))}</h6><ul>{nice_list}</ul>"
                  if nice_list else "")
    return f"""<details class='gaps'>
    <summary><span class='chips'>{chips}</span>
    <span class='small'>{escape(t('gaps.tap', lang))}</span></summary>
    <div class='gaps-detail'>{cov_col}
    <div class='col warn'><h5>⚠ {escape(t('gaps.not_in_profile', lang))}</h5>{must_block}{nice_block}
    <p class='small'>{escape(t('gaps.honest', lang))}</p></div></div></details>"""


# ---------- routes (order matters: /profiles/new before /profiles/{pid}) ----------
@router.get("/profiles/new", response_class=HTMLResponse)
def profile_new(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    lang = current_lang(request)
    return page(_profile_form("/profiles", {}, t("form.new_profile", lang), lang=lang), u,
                lang=lang, switch_urls=SWITCH_URLS)


@router.post("/profiles")
def profile_create(request: Request, name: str = Form(""), target_roles: str = Form(""),
                   skills: str = Form(""), experience: str = Form(""),
                   languages: str = Form(""), english_level: str = Form("B2"),
                   location_pref: str = Form(""), remote_pref: str = Form("remote"),
                   country: str = Form("Bulgaria"), relocate: str = Form(""),
                   salary_expectation: str = Form(""), min_match: str = Form("65"),
                   db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    lang = current_lang(request)
    errors, name, mm = _validate_profile(name, min_match, english_level, remote_pref,
                                         salary_expectation, lang)
    v = dict(name=name, target_roles=target_roles, skills=skills, experience=experience,
             languages=languages, english_level=english_level, location_pref=location_pref,
             remote_pref=remote_pref, country=country, relocate=bool(relocate),
             salary_expectation=salary_expectation, min_match=min_match)
    if errors:
        return page(_profile_form("/profiles", v, t("form.new_profile", lang), errors, lang), u,
                    lang=lang, switch_urls=SWITCH_URLS)
    p = Profile(user_id=u.id, name=name, target_roles=target_roles, skills=skills,
                experience=experience, languages=languages, english_level=english_level,
                location_pref=location_pref, remote_pref=remote_pref,
                country=(country or "Bulgaria").strip()[:64], relocate=bool(relocate),
                salary_expectation=salary_expectation, min_match=mm)
    db.add(p); db.commit(); db.refresh(p)
    return redirect(f"/profiles/{p.id}")


@router.get("/profiles/{pid}/edit", response_class=HTMLResponse)
def profile_edit_form(pid: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    lang = current_lang(request)
    if not p or p.user_id != u.id:
        return page(f"<div class='card'>{escape(t('app.not_found', lang))}</div>", u,
                    lang=lang, switch_urls=SWITCH_URLS)
    v = dict(name=p.name, target_roles=p.target_roles, skills=p.skills, experience=p.experience,
             languages=p.languages, english_level=p.english_level, location_pref=p.location_pref,
             remote_pref=p.remote_pref, country=p.country, relocate=p.relocate,
             salary_expectation=p.salary_expectation, min_match=p.min_match)
    delete_card = f"""<div class='card' style='border-color:var(--red-soft)'>
    <h3 style='color:var(--red)'>{escape(t('form.delete_head', lang))}</h3>
    <p class='small'>{escape(t('form.delete_note', lang))}</p>
    <form method='post' action='/profiles/{pid}/delete'
      onsubmit="return confirm('{t('form.delete_confirm', lang)}')">
      <button class='btn danger'>{escape(t('form.delete_btn', lang))}</button></form></div>"""
    return page(_profile_form(f"/profiles/{pid}/edit", v, t("form.edit_profile", lang), lang=lang)
                + delete_card, u, lang=lang, switch_urls=SWITCH_URLS)


@router.post("/profiles/{pid}/edit")
def profile_update(pid: int, request: Request, name: str = Form(""), target_roles: str = Form(""),
                   skills: str = Form(""), experience: str = Form(""),
                   languages: str = Form(""), english_level: str = Form("B2"),
                   location_pref: str = Form(""), remote_pref: str = Form("remote"),
                   country: str = Form("Bulgaria"), relocate: str = Form(""),
                   salary_expectation: str = Form(""), min_match: str = Form("65"),
                   db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    lang = current_lang(request)
    if not p or p.user_id != u.id:
        return page(f"<div class='card'>{escape(t('app.not_found', lang))}</div>", u,
                    lang=lang, switch_urls=SWITCH_URLS)
    errors, name, mm = _validate_profile(name, min_match, english_level, remote_pref,
                                         salary_expectation, lang)
    v = dict(name=name, target_roles=target_roles, skills=skills, experience=experience,
             languages=languages, english_level=english_level, location_pref=location_pref,
             remote_pref=remote_pref, country=country, relocate=bool(relocate),
             salary_expectation=salary_expectation, min_match=min_match)
    if errors:
        return page(_profile_form(f"/profiles/{pid}/edit", v, t("form.edit_profile", lang),
                                  errors, lang), u, lang=lang, switch_urls=SWITCH_URLS)
    p.name, p.target_roles, p.skills = name, target_roles, skills
    p.experience, p.languages, p.english_level = experience, languages, english_level
    p.location_pref, p.remote_pref = location_pref, remote_pref
    p.country, p.relocate = (country or "Bulgaria").strip()[:64], bool(relocate)
    p.salary_expectation, p.min_match = salary_expectation, mm
    p.embedding = None  # profile text changed → drop any cached vector
    # the profile's matches were computed against the OLD skills/targets — clear them so the
    # feed doesn't keep showing stale matches (e.g. ML jobs after removing an ML skill);
    # the next Search now rebuilds them against the edited profile.
    db.execute(delete(Match).where(Match.profile_id == p.id))
    db.commit()
    return redirect(f"/profiles/{p.id}")


@router.post("/profiles/{pid}/delete")
def profile_delete(pid: int, request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    db.delete(p); db.commit()  # matches cascade via FK ondelete
    return redirect("/")


@router.post("/profiles/{pid}/min_match")
def profile_set_min_match(pid: int, request: Request, min_match: str = Form("65"),
                          db: Session = Depends(get_db)):
    """Lightweight threshold tuner from the list view (no full edit round-trip). This is the
    same min_match that will later filter auto-fetched matches — see ROADMAP onboarding."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    try:
        mm = int(min_match)
    except (TypeError, ValueError):
        mm = p.min_match
    p.min_match = max(0, min(100, mm))
    db.commit()
    return redirect(f"/profiles/{p.id}")


@router.post("/profiles/{pid}/search")
def profile_search(pid: int, request: Request, db: Session = Depends(get_db)):
    """DB-first search: score this profile against the postings already in our index — no
    network on the user's path (sub-second). The index itself is refreshed on a schedule
    (INGEST_EVERY_HOURS) and by the daily job."""
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    started = datetime.utcnow()
    stats = RunStats()
    err = ""
    try:
        res = search_db(db, p, stats=stats)
    except Exception as e:  # noqa: BLE001 — degrade gracefully, still record the run
        err = str(e)
        res = {"pool": 0, "filtered": 0, "matched": 0}
        db.rollback()   # a failed flush poisons the session; recover before record_run
    try:
        record_run(db, "search_now", stats, started, ok=not err, error=err)
    except Exception:  # noqa: BLE001 — metrics are best-effort, never a 500 for the user
        db.rollback()
    return redirect(f"/profiles/{p.id}?pool={res['pool']}"
                    f"&filtered={res['filtered']}&found={res['matched']}")


# ---------- the one-page app (control strip + match feed) ----------
def _busy_js(lang: str) -> str:
    return ("onsubmit=\"var b=this.querySelector('button');"
            f"setTimeout(function(){{b.disabled=true;b.textContent='{t('app.generating', lang)}';}},0);\"")


def _source_host(post: Posting) -> str:
    """Short host label showing WHERE a posting came from ('dev.bg', 'remoteok.com'...) —
    owner feedback: with no source shown, the feed felt like it was dev.bg-only."""
    from urllib.parse import urlparse
    try:
        host = urlparse(post.url or post.apply_url or "").netloc
    except ValueError:
        return ""
    return host.removeprefix("www.").removeprefix("boards.").removeprefix("jobs.")


def _match_card(p: Profile, m: Match, post: Posting, docs: list[Document],
                lang: str = "en") -> str:
    meta = []
    if post.company:
        meta.append(f"<span class='m'>{icon('building', 'icon sm')}{escape(post.company)}</span>")
    if post.location:
        meta.append(f"<span class='m'>{icon('pin', 'icon sm')}{escape(post.location)}</span>")
    host = _source_host(post)
    if host:
        meta.append(f"<span class='m source'>{icon('globe', 'icon sm')}{escape(host)}</span>")
    meta_html = f"<div class='meta'>{''.join(meta)}</div>" if meta else ""

    docs_html = ""
    if docs:
        # show only the LATEST document per (kind, lang) — regenerations were stacking up as
        # six identical "Letter (EN)" links. docs arrive newest-first.
        latest: dict[tuple[str, str], Document] = {}
        for d in docs:
            latest.setdefault((d.kind, d.lang), d)
        links = []
        for d in latest.values():
            ic = "doc" if d.kind == "cv" else "mail"
            label = t("app.cv", lang) if d.kind == "cv" else t("app.letter", lang)
            links.append(f"<a href='/documents/{d.id}'>{icon(ic, 'icon')}"
                         f"{escape(label)} ({escape(d.lang.upper())})</a>")
        docs_html = (f"<div class='docs'><span class='label'>{escape(t('app.your_docs', lang))}</span>"
                     + "<span class='sep'>·</span>".join(links) + "</div>")

    busy = _busy_js(lang)
    apply_btn = (f"<a class='btn green' href='{escape(post.apply_url or post.url)}' "
                 f"target='_blank'>{icon('plane')}{escape(t('app.apply', lang))}</a>"
                 if (post.apply_url or post.url) else "")
    gen = (f"<form method='post' action='/profiles/{p.id}/postings/{post.id}/generate' style='display:inline' {busy}>"
           f"<input type='hidden' name='kind' value='cv'>"
           f"<button class='btn gray small' title=\"{escape(t('app.cv_title', lang))}\">{icon('doc')}{escape(t('app.cv', lang))}</button></form>"
           f"<form method='post' action='/profiles/{p.id}/postings/{post.id}/generate' style='display:inline' {busy}>"
           f"<input type='hidden' name='kind' value='cover_letter'>"
           f"<button class='btn gray small' title=\"{escape(t('app.letter_title', lang))}\">{icon('mail')}{escape(t('app.letter', lang))}</button></form>")
    return (f"<div class='match-card'>{_score_ring(m.score)}<div class='body'>"
            f"<div class='title'>{escape(post.title)}</div>{meta_html}"
            f"{_gaps_block(m.covered, m.missing, lang)}{docs_html}"
            f"<div class='actions'>{apply_btn}{gen}</div></div></div>")


def render_app(db: Session, u, active: Profile, profiles: list[Profile],
               pool=None, filtered=None, found=None, gen_err=None,
               lang: str = "en") -> str:
    """The single logged-in screen: control strip (profile tabs + threshold + Search now) and
    the match feed for the active profile. Used by both / and /profiles/{id}."""
    p = active
    # loading feedback: tab navigation and Search now both take seconds (live source fetches) —
    # без индикация изглеждат счупени (owner feedback), so both show a busy state instantly.
    tab_busy = "onclick=\"this.textContent='⏳ ' + this.textContent;\""
    tabs = "".join(
        f"<a class='tab{' active' if pr.id == p.id else ''}' href='/profiles/{pr.id}' "
        f"{tab_busy if pr.id != p.id else ''}>{escape(pr.name)}</a>"
        for pr in profiles)
    tabs += f"<a class='tab add' href='/onboarding' {tab_busy}>{escape(t('app.new_tab', lang))}</a>"
    search_busy = ("onsubmit=\"var b=this.querySelector('button');"
                   "setTimeout(function(){b.disabled=true;"
                   f"b.textContent='{t('app.searching', lang)}';}},0);\"")

    strip = f"""<div class='control-strip'>
    <div class='profile-tabs'>{tabs}</div>
    <form method='post' action='/profiles/{p.id}/min_match' class='mini-tuner'>
      <label for='mm' style='margin:0'>{escape(t('app.matches_ge', lang))}</label>
      <input id='mm' name='min_match' type='number' min='0' max='100' value='{p.min_match}'>
      <span class='value'>{escape(t('app.min', lang))} {p.min_match}%</span>
      <button class='btn gray small'>{escape(t('app.apply_thresh', lang))}</button></form>
    <a class='btn gray small' href='/profiles/{p.id}/edit' title=\"{escape(t('app.edit_title', lang))}\">{icon('edit')}{escape(t('app.edit', lang))}</a>
    <form method='post' action='/profiles/{p.id}/search' style='margin:0' {search_busy}>
      <button class='btn green search-now'>{icon('search')}{escape(t('app.search_now', lang))}</button></form>
    </div>"""

    banner = ""
    if gen_err:
        banner += (f"<div class='card' style='border-color:var(--red);background:var(--red-soft)'>"
                   f"<b style='color:var(--red)'>{escape(t('app.gen_failed', lang))}</b> {escape(gen_err)}</div>")
    if found is not None:
        filt = t("app.filtered", lang).format(n=filtered) if filtered else ""
        done = t("app.search_done", lang).format(pool=pool or 0,
                                                 filt=filt, found=found, min=p.min_match)
        banner += (f"<div class='card' style='background:var(--green-soft);border-color:var(--green)'>"
                   f"{done}</div>")

    q = (select(Match, Posting).join(Posting, Match.posting_id == Posting.id)
         .where(Match.profile_id == p.id, Match.score >= p.min_match,
                Posting.is_live.is_(True))     # retired (>1 month old) postings never show
         .order_by(Match.score.desc()))
    pairs = db.execute(q).all()
    # documents per posting, one query
    docs_by_post: dict[int, list[Document]] = {}
    for d in db.execute(select(Document).where(Document.user_id == u.id)
                        .order_by(Document.created_at.desc())).scalars().all():
        if d.posting_id:
            docs_by_post.setdefault(d.posting_id, []).append(d)

    cards = []
    for i, (m, post) in enumerate(pairs):
        cards.append(_match_card(p, m, post, docs_by_post.get(post.id, []), lang))
        if i == 0:
            cards.append("<div class='ad-slot'>Ad space</div>")   # hidden until activated (M1)
    feed = "".join(cards) or (
        f"<div class='empty-state'><h3>{escape(t('app.empty_head', lang))}</h3>"
        f"<p>{escape(t('app.empty_body', lang))}</p></div>")

    scaffold = f"""<details class='card'><summary class='small' style='cursor:pointer'>
    {escape(t('app.add_posting', lang))}</summary>
    <form method='post' action='/profiles/{p.id}/postings' style='margin-top:12px'>
      <label>{escape(t('app.job_url', lang))}</label><input name='url' placeholder='https://...'>
      <label>{escape(t('app.apply_url', lang))}</label><input name='apply_url'>
      <div class='row2'><div><label>{escape(t('app.title', lang))}</label><input name='title'></div>
      <div><label>{escape(t('app.company', lang))}</label><input name='company'></div></div>
      <label>{escape(t('app.location', lang))}</label><input name='location'>
      <label>{escape(t('app.description', lang))}</label><textarea name='description' rows='6'></textarea>
      <p style='margin-top:12px'><button class='btn'>{escape(t('app.score_it', lang))}</button></p></form></details>"""

    act = get_activity(db, u.id)
    return page(banner + strip + feed + scaffold, u,
                title=f"{p.name} — Job Agent", lang=lang, switch_urls=SWITCH_URLS,
                paused=bool(act.found_job) if act else False)


@router.get("/profiles/{pid}", response_class=HTMLResponse)
def profile_view(pid: int, request: Request, db: Session = Depends(get_db),
                 pool: int | None = None,
                 filtered: int | None = None, found: int | None = None,
                 gen_err: str | None = None):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    lang = current_lang(request)
    if not p or p.user_id != u.id:
        return page(f"<div class='card'>{escape(t('app.not_found', lang))}</div>", u,
                    lang=lang, switch_urls=SWITCH_URLS)
    profiles = db.execute(select(Profile).where(Profile.user_id == u.id)
                          .order_by(Profile.created_at)).scalars().all()
    return render_app(db, u, p, profiles, pool=pool,
                      filtered=filtered, found=found, gen_err=gen_err, lang=lang)


@router.post("/profiles/{pid}/postings")
def add_posting(pid: int, request: Request, url: str = Form(""), apply_url: str = Form(""),
                title: str = Form(""), company: str = Form(""), location: str = Form(""),
                description: str = Form(""), db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    p = db.get(Profile, pid)
    if not p or p.user_id != u.id:
        return redirect("/")
    chash = hashlib.sha256((url or title + company + description).encode("utf-8")).hexdigest()[:64]
    post = db.execute(select(Posting).where(Posting.content_hash == chash)).scalar_one_or_none()
    if not post:
        reqs = extract_requirements(description)  # rules-based: must/nice/resp, no LLM cost
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
    return redirect(f"/profiles/{p.id}")
