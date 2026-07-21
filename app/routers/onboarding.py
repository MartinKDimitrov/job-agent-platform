"""Light onboarding: pick an occupation, get its typical skills as editable chips, create a
profile in ~30 seconds. Server-rendered with a tiny bit of vanilla JS for the chip suggestions
(no SPA); the skill autocomplete uses a native <datalist>. See ROADMAP "Onboarding"."""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Profile
from ..taxonomy import OCCUPATIONS, by_id, all_skills
from ..web import page, current_user, redirect, escape

router = APIRouter()

# Bulgaria-primary defaults (remote not neglected): remote jobs pass, and onsite jobs in these
# cities pass; onsite abroad is filtered by the location hard filter.
_DEFAULT_LOCATION = "Bulgaria, Sofia, Varna"


@router.get("/onboarding", response_class=HTMLResponse)
def onboarding_form(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    options = "".join(
        f"<option value='{escape(o['id'])}'>{escape(o['bg'])}</option>" for o in OCCUPATIONS)
    datalist = "".join(f"<option value=\"{escape(s)}\">" for s in all_skills())
    tax_json = json.dumps({o["id"]: {"skills": o["skills"]} for o in OCCUPATIONS},
                          ensure_ascii=False)
    body = f"""<div class='card'><h2>Quick start — build your profile</h2>
    <p class='small'>Pick your profession and we'll suggest the typical skills. Tweak them, then
    create your profile.</p>
    <form method='post' action='/onboarding'>
      <label>Profession</label>
      <select name='occupation' id='occ' required>
        <option value='' disabled selected>Choose…</option>{options}
      </select>
      <label style='margin-top:10px'>Skills <span class='small'>(uncheck any that don't fit)</span></label>
      <div id='skills' class='small'>Select a profession to see suggested skills.</div>
      <label style='margin-top:10px'>Add more skills (comma-separated)</label>
      <input name='extra_skills' list='skilllist' placeholder='e.g. GraphQL, Terraform'>
      <datalist id='skilllist'>{datalist}</datalist>
      <p style='margin-top:12px'><button class='btn'>Create profile</button>
      <a class='btn gray' href='/profiles/new'>Use the full form</a></p>
    </form></div>
    <script>
    const TAX = {tax_json};
    document.getElementById('occ').addEventListener('change', function() {{
      const o = TAX[this.value], box = document.getElementById('skills');
      box.innerHTML = '';
      if (!o) return;
      o.skills.forEach(function(s) {{
        const w = document.createElement('label');
        w.style.cssText = 'display:inline-block;margin:3px 8px 3px 0;font-size:13px;color:#222';
        const cb = document.createElement('input');
        cb.type = 'checkbox'; cb.name = 'skills'; cb.value = s; cb.checked = true;
        cb.style.width = 'auto';
        w.appendChild(cb); w.appendChild(document.createTextNode(' ' + s));
        box.appendChild(w);
      }});
    }});
    </script>"""
    return page(body, u, title="Quick start — Job Agent")


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
