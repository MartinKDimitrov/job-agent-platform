"""Light onboarding: pick an occupation, get its typical skills as editable chips, create a
profile in ~30 seconds. Server-rendered with a tiny bit of vanilla JS for the chip suggestions
(no SPA); the skill autocomplete uses a native <datalist>. See ROADMAP "Onboarding"."""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Profile
from ...domain.taxonomy import OCCUPATIONS, by_id, all_skills
from ..web import page, current_user, redirect, escape
from ..i18n import t, current_lang

router = APIRouter()

from ..i18n import SWITCH_URLS  # noqa: F811 — cookie-based switcher, all languages

# Bulgaria-primary defaults (remote not neglected): remote jobs pass, and onsite jobs in these
# cities pass; onsite abroad is filtered by the location hard filter.
_DEFAULT_LOCATION = "Bulgaria, Sofia, Varna"


def onboarding_card(heading: str | None = None, sub: str | None = None,
                    lang: str = "en") -> str:
    """The onboarding card + chip script — reused by /onboarding and by the one-page home for
    brand-new users (the empty state IS the onboarding, no navigation)."""
    heading = heading if heading is not None else t("ob.head", lang)
    sub = sub if sub is not None else t("ob.sub", lang)
    # occupation labels follow the UI language (taxonomy carries both en and bg names)
    options = "".join(
        f"<option value='{escape(o['id'])}'>{escape(o.get(lang) or o['en'])}</option>"
        for o in OCCUPATIONS)
    datalist = "".join(f"<option value=\"{escape(s)}\">" for s in all_skills())
    tax_json = json.dumps({o["id"]: {"skills": o["skills"]} for o in OCCUPATIONS},
                          ensure_ascii=False)
    steps = f"""<div class='mini-steps' aria-label='{escape(t('ob.how', lang))}'>
    <div class='s'><span class='n'>1</span><span class='t'>{escape(t('ob.step1', lang))}</span></div>
    <div class='s'><span class='n'>2</span><span class='t'>{escape(t('ob.step2', lang))}</span></div>
    <div class='s'><span class='n'>3</span><span class='t'>{escape(t('ob.step3', lang))}</span></div>
    </div>"""
    return f"""{steps}<div class='card'><h2>{escape(heading)}</h2>
    <p class='small'>{escape(sub)}</p>
    <form method='post' action='/onboarding'>
      <label>{escape(t('ob.profession', lang))}</label>
      <select name='occupation' id='occ' required>
        <option value='' disabled selected>{escape(t('ob.choose', lang))}</option>{options}
      </select>
      <div style='margin-top:16px'>
      <label>{escape(t('ob.skills', lang))} <span class='small'>{escape(t('ob.tap', lang))}</span></label>
      <div id='skills' class='small'>{escape(t('ob.select_first', lang))}</div></div>
      <div style='margin-top:16px'>
      <label>{escape(t('ob.more', lang))}</label>
      <input name='extra_skills' list='skilllist' placeholder='GraphQL, Terraform…'>
      <datalist id='skilllist'>{datalist}</datalist></div>
      <p style='margin-top:18px'><button class='btn big block'>{escape(t('ob.create', lang))}</button></p>
      <p class='small center'><a href='/profiles/new'>{escape(t('ob.full_form', lang))}</a> ·
      {escape(t('ob.change_later', lang))}</p>
    </form></div>
    <script>
    const TAX = {tax_json};
    document.getElementById('occ').addEventListener('change', function() {{
      const o = TAX[this.value], box = document.getElementById('skills');
      box.innerHTML = '';
      if (!o) return;
      box.style.display = 'flex'; box.style.flexWrap = 'wrap'; box.style.gap = '8px';
      o.skills.forEach(function(s) {{
        const w = document.createElement('label');
        w.className = 'chip toggle on';
        w.style.margin = '0';
        const cb = document.createElement('input');
        cb.type = 'checkbox'; cb.name = 'skills'; cb.value = s; cb.checked = true;
        cb.style.display = 'none';
        w.appendChild(cb); w.appendChild(document.createTextNode(s));
        w.addEventListener('click', function(e) {{
          e.preventDefault();
          cb.checked = !cb.checked;
          w.classList.toggle('on', cb.checked);
        }});
        box.appendChild(w);
      }});
    }});
    </script>"""


@router.get("/onboarding", response_class=HTMLResponse)
def onboarding_form(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    lang = current_lang(request)
    return page(onboarding_card(lang=lang), u, title=t("ob.title", lang),
                lang=lang, switch_urls=SWITCH_URLS)


@router.post("/onboarding")
def onboarding_create(request: Request, occupation: str = Form(""),
                      skills: list[str] = Form(default=[]), extra_skills: str = Form(""),
                      db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    occ = by_id(occupation)
    if not occ:
        return redirect("/onboarding")
    extras = [s.strip() for s in extra_skills.split(",") if s.strip()]
    # de-dup while keeping order (checked suggestions first, then free-text additions)
    ordered, seen = [], set()
    for s in list(skills) + extras:
        key = s.lower()
        if s and key not in seen:
            seen.add(key)
            ordered.append(s)
    p = Profile(user_id=u.id, name=occ["en"], target_roles=occ["en"],
                skills=", ".join(ordered), languages="Bulgarian, English", english_level="B2",
                location_pref=_DEFAULT_LOCATION, remote_pref="remote", min_match=65)
    db.add(p); db.commit(); db.refresh(p)
    return redirect(f"/profiles/{p.id}")
