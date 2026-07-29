"""Hierarchical onboarding (Stage 2): general info → category → subcategory → occupation →
qualifications with years-of-practice. Server-rendered single page; the drill-down and skill
pre-fill come from small JSON endpoints backed by the ESCO taxonomy (taxonomy_repo). Years are
stored inline in the existing Profile.skills field ("Kotlin 5y, …") which scoring already parses,
so no scoring change. Falls back cleanly when a taxonomy isn't loaded for a language."""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...data.db import get_db
from ...data.models import Profile, Occupation
from ...data import taxonomy_repo as tx
from ...domain.filters import _CITY_ALIASES
from ..web import page, current_user, redirect, escape
from ..i18n import t, current_lang
from ..i18n import SWITCH_URLS  # noqa: F401 — re-exported for auth.py's post-signup card

router = APIRouter()

# Category display (order + labels) for the loaded verticals. Anything loaded but unlisted still
# shows, labelled by its raw key.
_VERTICAL_META = {
    "ict":        {"bg": "ИТ и софтуер", "en": "IT & Software", "icon": "💻"},
    "finance":    {"bg": "Финанси и счетоводство", "en": "Finance & Accounting", "icon": "📊"},
    "healthcare": {"bg": "Здравеопазване", "en": "Healthcare", "icon": "🩺"},
    "sales":      {"bg": "Продажби и маркетинг", "en": "Sales & Marketing", "icon": "🛍️"},
    "engineering": {"bg": "Инженерство и техника", "en": "Engineering & Science", "icon": "⚙️"},
    "education":  {"bg": "Образование", "en": "Education", "icon": "🎓"},
    "management": {"bg": "Мениджмънт", "en": "Management", "icon": "📈"},
    "legal_culture": {"bg": "Право, социални и културни", "en": "Legal, Social & Culture", "icon": "⚖️"},
    "admin":      {"bg": "Администрация", "en": "Administration", "icon": "🗂️"},
    "personal_services": {"bg": "Услуги и гостоприемство", "en": "Services & Hospitality", "icon": "🛎️"},
    "construction": {"bg": "Строителство", "en": "Construction", "icon": "🏗️"},
    "crafts":     {"bg": "Занаяти и производство", "en": "Crafts & Manufacturing", "icon": "🔧"},
    "machine_ops": {"bg": "Машини и транспорт", "en": "Machinery & Transport", "icon": "🚚"},
    "agriculture": {"bg": "Селско стопанство", "en": "Agriculture", "icon": "🌾"},
    "elementary": {"bg": "Общи услуги", "en": "Elementary Occupations", "icon": "🧹"},
    "military":   {"bg": "Отбрана и сигурност", "en": "Defence & Security", "icon": "🛡️"},
    "other":      {"bg": "Други", "en": "Other", "icon": "•"},
}
_VERTICAL_ORDER = ["ict", "finance", "healthcare", "sales", "engineering", "education", "management",
                   "legal_culture", "admin", "personal_services", "construction", "crafts",
                   "machine_ops", "agriculture", "elementary", "military"]

# Country → its cities (dependent dropdowns). Cities mirror the matcher's vocabulary
# (filters._CITY_ALIASES) so a chosen location is one the geo filter actually understands.
# Bulgaria first (primary market), then EU hubs alphabetically.
_COUNTRY_CITIES: dict[str, list[str]] = {
    "Bulgaria": ["Sofia", "Plovdiv", "Varna", "Burgas", "Ruse", "Stara Zagora", "Pleven",
                 "Sliven", "Dobrich", "Shumen", "Pernik", "Haskovo", "Pazardzhik", "Blagoevgrad",
                 "Veliko Tarnovo", "Gabrovo", "Vratsa", "Kazanlak", "Vidin", "Kardzhali", "Montana"],
    "Austria": ["Vienna"],
    "Belgium": ["Brussels"],
    "Czechia": ["Prague"],
    "Denmark": ["Copenhagen"],
    "Finland": ["Helsinki"],
    "France": ["Paris", "Lyon"],
    "Germany": ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne", "Stuttgart", "Duesseldorf"],
    "Greece": ["Athens", "Thessaloniki"],
    "Hungary": ["Budapest"],
    "Ireland": ["Dublin"],
    "Italy": ["Milan", "Rome"],
    "Netherlands": ["Amsterdam", "Rotterdam"],
    "Norway": ["Oslo"],
    "Poland": ["Warsaw", "Krakow", "Wroclaw", "Gdansk"],
    "Portugal": ["Lisbon", "Porto"],
    "Romania": ["Bucharest"],
    "Spain": ["Madrid", "Barcelona", "Valencia"],
    "Sweden": ["Stockholm"],
    "Switzerland": ["Zurich", "Geneva"],
    "United Kingdom": ["London", "Manchester"],
}


def _L(lang: str, bg: str, en: str) -> str:
    return bg if lang == "bg" else en


def _ordered_verticals(db: Session) -> list[str]:
    have = set(tx.verticals(db))
    ordered = [v for v in _VERTICAL_ORDER if v in have]
    return ordered + sorted(have - set(ordered))


# ---------------------------------------------------------------- JSON drill-down endpoints ----
@router.get("/onboarding/api/subcats")
def api_subcats(request: Request, vertical: str, db: Session = Depends(get_db)):
    return JSONResponse(tx.leaf_groups(db, vertical, current_lang(request)))


@router.get("/onboarding/api/occupations")
def api_occupations(request: Request, isco: str, db: Session = Depends(get_db)):
    return JSONResponse(tx.occupations(db, isco, current_lang(request)))


@router.get("/onboarding/api/search")
def api_search(request: Request, q: str, db: Session = Depends(get_db)):
    return JSONResponse(tx.search_occupations(db, q, current_lang(request)))


@router.get("/onboarding/api/skills")
def api_skills(request: Request, occupation_id: int, db: Session = Depends(get_db)):
    return JSONResponse(tx.occupation_skills(db, occupation_id, current_lang(request)))


@router.get("/onboarding/api/cities")
def api_cities(request: Request, country: str, q: str = "", db: Session = Depends(get_db)):
    """City autocomplete within a country. Backed by the GeoNames gazetteer once loaded
    (all EU settlements > 10k, multilingual); until then it serves the curated fallback list."""
    from ...data import city_repo
    return JSONResponse(city_repo.search(db, country, q, current_lang(request),
                                         fallback=_COUNTRY_CITIES))


# ------------------------------------------------------------------------------- the card -----
def onboarding_card(heading: str | None = None, sub: str | None = None,
                    lang: str = "en", db: Session | None = None) -> str:
    heading = heading if heading is not None else t("ob.head", lang)
    sub = sub if sub is not None else t("ob.sub", lang)
    verts = _ordered_verticals(db) if db is not None else []
    cat_buttons = "".join(
        f"<button type='button' class='cat' data-v='{escape(v)}'>"
        f"<span class='ic'>{_VERTICAL_META.get(v, {}).get('icon', '•')}</span>"
        f"{escape(_VERTICAL_META.get(v, {}).get(lang) or v.title())}</button>"
        for v in verts)
    from ...data import city_repo
    country_list = city_repo.countries(db, _COUNTRY_CITIES) if db is not None else list(_COUNTRY_CITIES)
    country_opts = "".join(
        f"<option{' selected' if c == 'Bulgaria' else ''}>{escape(c)}</option>"
        for c in country_list)
    remote_opts = "".join(
        f"<option value='{v}'{' selected' if v == 'remote' else ''}>{escape(lbl)}</option>"
        for v, lbl in (("remote", _L(lang, "Дистанционно", "Remote")),
                       ("hybrid", _L(lang, "Хибридно", "Hybrid")),
                       ("onsite", _L(lang, "В офис", "On-site")),
                       ("any", _L(lang, "Без значение", "Any"))))
    cefr = "".join(f"<option{' selected' if lv == 'B2' else ''}>{lv}</option>"
                   for lv in ("A1", "A2", "B1", "B2", "C1", "C2"))
    S = _step_strings(lang)
    return f"""
<div class='card ob' id='ob'>
  <h2 class='ob-title'>{escape(heading)}</h2>
  <p class='small'>{escape(sub)}</p>
  <div class='ob-steps'>
    <span class='st on' data-s='1'>1 · {escape(S['s1'])}</span>
    <span class='st' data-s='2'>2 · {escape(S['s2'])}</span>
    <span class='st' data-s='3'>3 · {escape(S['s3'])}</span>
    <span class='st' data-s='4'>4 · {escape(S['s4'])}</span>
  </div>

  <form method='post' action='/onboarding' id='obform'>
    <input type='hidden' name='occupation_id' id='f_occ'>
    <input type='hidden' name='skills_blob' id='f_skills'>

    <!-- STEP 1 — general -->
    <section class='ob-panel' data-s='1'>
      <h2>{escape(S['s1_h'])}</h2>
      <div class='grid2'>
        <label>{escape(S['country'])}<select name='country' id='f_country'>{country_opts}</select></label>
        <label class='ac-wrap'>{escape(S['city'])}
          <input name='location_pref' id='f_city' autocomplete='off' value='Sofia'
                 placeholder='{escape(S['city_ph'])}'>
          <div id='citylist' class='ac'></div></label>
        <label>{escape(S['work'])}<select name='remote_pref'>{remote_opts}</select></label>
        <label>{escape(S['english'])}<select name='english_level'>{cefr}</select></label>
        <label class='wide'>{escape(S['langs'])}<input name='languages' value='Bulgarian, English'></label>
        <label class='chk'><input type='checkbox' name='relocate' value='1'> {escape(S['relocate'])}</label>
      </div>
      <p class='ob-nav'><button type='button' class='btn big block' data-next='2'>{escape(S['next'])}</button></p>
    </section>

    <!-- STEP 2 — category -->
    <section class='ob-panel hide' data-s='2'>
      <h2>{escape(S['s2_h'])}</h2>
      <div class='cats'>{cat_buttons or "<p class='small'>—</p>"}</div>
      <p class='ob-nav'><a href='#' class='back' data-back='1'>{escape(S['back'])}</a></p>
    </section>

    <!-- STEP 3 — subcategory + occupation -->
    <section class='ob-panel hide' data-s='3'>
      <h2>{escape(S['s3_h'])}</h2>
      <input type='search' id='occsearch' placeholder='{escape(S['search'])}' autocomplete='off'>
      <div id='subcats' class='cats sub'></div>
      <div id='occlist' class='cats occ'></div>
      <p class='ob-nav'><a href='#' class='back' data-back='2'>{escape(S['back'])}</a></p>
    </section>

    <!-- STEP 4 — skills + years -->
    <section class='ob-panel hide' data-s='4'>
      <h2>{escape(S['s4_h'])} <span class='small' id='pickedocc'></span></h2>
      <p class='small'>{escape(S['s4_hint'])}</p>
      <div class='bulk-years'>
        <label>{escape(S['bulk_label'])}
          <input id='bulkyears' type='number' min='0' max='50' placeholder='5'></label>
        <button type='button' id='bulkapply' class='btn gray small'>{escape(S['bulk_apply'])}</button>
        <span class='small bh'>{escape(S['bulk_hint'])}</span>
      </div>
      <div class='sk-group'>
        <div class='sk-head'>{escape(S['core_skills'])} <span class='sk-sub'>· {escape(S['core_sub'])}</span></div>
        <div id='skills-ess' class='skills'></div>
      </div>
      <div class='sk-group' id='opt-group' style='display:none'>
        <button type='button' class='opt-toggle' id='opt-toggle'>
          {escape(S['more_skills'])} · <span id='opt-verb'>{escape(S['show_more'])}</span>
          <span id='opt-n' class='opt-n'></span></button>
        <div id='skills-opt' class='skills hide'></div>
      </div>
      <label style='margin-top:14px;display:block'>{escape(S['more'])}
        <input id='extra' name='extra_skills' placeholder='{escape(S['more_ph'])}'></label>
      <p class='ob-nav'><a href='#' class='back' data-back='3'>{escape(S['back'])}</a>
        <button class='btn big' id='create'>{escape(S['create'])}</button></p>
    </section>
  </form>
</div>
{_ob_style()}
<script>window.OB_YRS={json.dumps(S['yrs'])};window.OB_CRS={json.dumps(S['courses'])};
window.OB_SHOW={json.dumps(S['show_more'])};window.OB_HIDE={json.dumps(S['hide_more'])};
{_ob_script(lang)}</script>"""


def _step_strings(lang: str) -> dict:
    L = lambda bg, en: _L(lang, bg, en)  # noqa: E731
    return {
        "s1": L("За теб", "About you"), "s2": L("Област", "Field"),
        "s3": L("Професия", "Occupation"), "s4": L("Умения", "Skills"),
        "s1_h": L("Първо накратко за теб", "First, a bit about you"),
        "s2_h": L("В коя област търсиш работа?", "Which field are you in?"),
        "s3_h": L("Избери своята професия", "Pick your occupation"),
        "s4_h": L("Твоите квалификации", "Your qualifications"),
        "s4_hint": L("Отбележи какво владееш и въведи години практика за всяко.",
                     "Mark what you have and enter years of practice for each."),
        "country": L("Държава", "Country"), "city": L("Град", "City"),
        "city_ph": L("започни да пишеш…", "start typing…"),
        "work": L("Начин на работа", "Work type"), "english": L("Английски", "English"),
        "langs": L("Езици", "Languages"), "relocate": L("Готов/а съм да се преместя",
                                                        "Willing to relocate"),
        "search": L("или търси професия…", "or search occupations…"),
        "more": L("Още умения (по избор)", "More skills (optional)"),
        "more_ph": L("Excel, SAP, преговори…", "Excel, SAP, negotiation…"),
        "next": L("Напред →", "Next →"), "back": L("← Назад", "← Back"),
        "create": L("Създай профил", "Create profile"),
        "yrs": L("год.", "yrs"),
        "courses": L("само курс", "courses"),
        "bulk_label": L("Общ професионален стаж", "Total years of experience"),
        "bulk_apply": L("Попълни на избраните", "Apply to selected"),
        "bulk_hint": L("бърз старт — после можеш да коригираш всяко поотделно",
                       "quick start — you can fine-tune each afterwards"),
        "core_skills": L("Основни умения", "Core skills"),
        "core_sub": L("типични за професията — маркирани по подразбиране",
                      "typical for this occupation — selected by default"),
        "more_skills": L("Допълнителни умения", "Additional skills"),
        "show_more": L("Покажи още", "Show more"),
        "hide_more": L("Скрий", "Hide"),
    }


def _ob_style() -> str:
    return """<style>
    #ob .ob-steps{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 18px;font-size:12px}
    #ob .st{padding:4px 10px;border-radius:20px;background:var(--line,#e5e8ee);color:var(--muted,#667)}
    #ob .st.on{background:var(--accent,#2f6feb);color:#fff}
    #ob .ob-panel{animation:obin .2s ease}
    #ob .ob-panel.hide{display:none}
    @keyframes obin{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
    #ob .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    #ob .grid2 label{display:flex;flex-direction:column;gap:4px;font-size:13px}
    #ob .grid2 label.wide{grid-column:1/-1}
    #ob .grid2 label.chk{flex-direction:row;align-items:center;gap:8px;grid-column:1/-1;
      margin-top:2px;cursor:pointer;font-size:13.5px}
    #ob .grid2 label.chk input{width:16px;height:16px;flex:0 0 auto}
    #ob .ac-wrap{position:relative}
    #ob .ac{position:absolute;left:0;right:0;top:100%;z-index:20;background:var(--panel,#fff);
      border:1px solid var(--line,#e5e8ee);border-radius:8px;margin-top:2px;max-height:220px;
      overflow:auto;display:none;box-shadow:0 6px 20px rgba(0,0,0,.08)}
    #ob .ac.show{display:block}
    #ob .ac div{padding:8px 12px;cursor:pointer;font-size:14px}
    #ob .ac div:hover,#ob .ac div.sel{background:var(--line,#eef1f6)}
    #ob .cats{display:flex;flex-wrap:wrap;gap:10px;margin:6px 0}
    #ob .cat,#ob .sc,#ob .oc{border:1px solid var(--line,#e5e8ee);background:var(--panel,#fff);
      border-radius:10px;padding:12px 16px;cursor:pointer;font-size:15px;text-align:left}
    #ob .cat{display:flex;align-items:center;gap:10px;min-width:150px}
    #ob .cat .ic{font-size:20px}
    #ob .sc.on,#ob .oc.on,#ob .cat:hover,#ob .sc:hover,#ob .oc:hover{border-color:var(--accent,#2f6feb)}
    #ob .cats.sub .sc{font-size:14px;padding:9px 13px}
    #ob .cats.occ{flex-direction:column;margin-top:10px}
    #ob #occsearch{width:100%;margin:6px 0 4px;padding:9px 12px}
    #ob .bulk-years{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:6px 0 14px;
      padding:12px 14px;background:var(--accent-soft,#eef4ff);border:1px solid var(--line,#dbe3ea);
      border-radius:10px}
    #ob .bulk-years label{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:600}
    #ob .bulk-years input{width:64px;padding:5px 8px;border-radius:7px;
      border:1px solid var(--line,#c9cfdb)}
    #ob .bulk-years .bh{color:var(--muted,#778);font-weight:400;flex:1 1 160px}
    #ob .sk-group{margin-bottom:14px}
    #ob .sk-head{font-size:13px;font-weight:600;color:var(--ink,#222);margin:0 0 8px}
    #ob .sk-sub{font-weight:400;color:var(--muted,#889);font-size:12px}
    #ob .opt-toggle{background:none;border:1px dashed var(--line,#c9cfdb);border-radius:8px;
      padding:8px 12px;cursor:pointer;font-size:13px;color:var(--accent-ink,#2b62d6);font-weight:600}
    #ob .opt-toggle .opt-n{color:var(--muted,#889);font-weight:400;margin-left:2px}
    #ob #skills-opt{margin-top:10px}
    #ob #skills-opt.hide{display:none}
    #ob .skills{display:flex;flex-wrap:wrap;gap:8px}
    #ob .skill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line,#e5e8ee);
      border-radius:20px;padding:4px 6px 4px 12px;font-size:13px;opacity:.55}
    #ob .skill.on{opacity:1;border-color:var(--accent,#2f6feb);background:var(--accent-soft,#eef4ff)}
    #ob .skill.ess .lbl::after{content:' •';color:var(--accent,#2f6feb)}
    #ob .skill .lbl{cursor:pointer}
    #ob .skill .yrs{width:44px;padding:2px 4px;font-size:12px;border-radius:6px;
      border:1px solid var(--line,#e5e8ee);display:none}
    #ob .skill.on .yrs{display:inline-block}
    #ob .skill .yl{font-size:11px;color:var(--muted,#889);display:none}
    #ob .skill.on .yl{display:inline}
    #ob .skill .crs{display:none;font-size:11px;padding:1px 7px;border-radius:10px;cursor:pointer;
      border:1px dashed var(--line,#c9cfdb);color:var(--muted,#778)}
    #ob .skill.on .crs{display:inline}
    #ob .skill.crs-on .crs{background:var(--accent,#2f6feb);color:#fff;border-style:solid}
    #ob .skill.crs-on .yrs,#ob .skill.crs-on .yl{opacity:.35}
    #ob .ob-nav{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px}
    #ob .ob-nav .back{color:var(--muted,#667);font-size:14px}
    </style>"""


def _ob_script(lang: str) -> str:
    return r"""
(function(){
  var ob=document.getElementById('ob'); if(!ob) return;
  var qs=function(s){return ob.querySelector(s);};
  function show(n){
    ob.querySelectorAll('.ob-panel').forEach(function(p){p.classList.toggle('hide',p.dataset.s!=String(n));});
    ob.querySelectorAll('.st').forEach(function(s){s.classList.toggle('on',Number(s.dataset.s)<=n);});
  }
  function debounce(fn,ms){var t;return function(){var a=arguments,c=this;clearTimeout(t);
    t=setTimeout(function(){fn.apply(c,a);},ms);};}
  async function getJSON(u){var r=await fetch(u);return r.json();}

  // step nav
  ob.querySelectorAll('[data-next]').forEach(function(b){b.onclick=function(){show(Number(b.dataset.next));};});
  ob.querySelectorAll('[data-back]').forEach(function(a){a.onclick=function(e){e.preventDefault();show(Number(a.dataset.back));};});

  // country -> city autocomplete
  var country=qs('#f_country'), city=qs('#f_city'), clist=qs('#citylist');
  async function loadCities(){
    var data=await getJSON('/onboarding/api/cities?country='+encodeURIComponent(country.value)+'&q='+encodeURIComponent(city.value.trim()));
    clist.innerHTML='';
    data.forEach(function(c){var d=document.createElement('div');d.textContent=c.name;
      d.onclick=function(){city.value=c.name;clist.classList.remove('show');};clist.appendChild(d);});
    clist.classList.toggle('show',data.length>0);
  }
  country.addEventListener('change',function(){city.value='';loadCities();});
  city.addEventListener('input',debounce(loadCities,180));
  city.addEventListener('focus',loadCities);
  document.addEventListener('click',function(e){if(!clist.contains(e.target)&&e.target!=city)clist.classList.remove('show');});

  // category -> subcats -> occupations
  var f_occ=qs('#f_occ');
  ob.querySelectorAll('.cat').forEach(function(b){b.onclick=async function(){
    show(3); qs('#occsearch').value=''; qs('#occlist').innerHTML='';
    var data=await getJSON('/onboarding/api/subcats?vertical='+encodeURIComponent(b.dataset.v));
    var box=qs('#subcats'); box.innerHTML='';
    data.forEach(function(g){var s=document.createElement('button');s.type='button';s.className='sc';
      s.textContent=g.label;s.onclick=function(){selectSub(s);loadOccs(g.isco_code);};box.appendChild(s);});
  };});
  function selectSub(el){qs('#subcats').querySelectorAll('.sc').forEach(function(x){x.classList.remove('on');});el.classList.add('on');}
  async function loadOccs(isco){renderOccs(await getJSON('/onboarding/api/occupations?isco='+encodeURIComponent(isco)));}
  function renderOccs(list){var box=qs('#occlist');box.innerHTML='';
    list.forEach(function(o){var b=document.createElement('button');b.type='button';b.className='oc';
      b.textContent=o.label;b.onclick=function(){pickOcc(o);};box.appendChild(b);});}
  qs('#occsearch').addEventListener('input',debounce(async function(e){
    var q=e.target.value.trim(); if(q.length<2){return;}
    qs('#subcats').querySelectorAll('.sc').forEach(function(x){x.classList.remove('on');});
    renderOccs(await getJSON('/onboarding/api/search?q='+encodeURIComponent(q)));},220));
  qs('#occsearch').addEventListener('keydown',function(e){if(e.key==='Enter')e.preventDefault();});

  function makeChip(s, selected){
    var chip=document.createElement('span'); chip.className='skill'+(s.essential?' ess':'')+(selected?' on':'');
    chip.dataset.label=s.label;
    var lbl=document.createElement('span'); lbl.className='lbl'; lbl.textContent=s.label;
    lbl.onclick=function(){chip.classList.toggle('on');};
    var yr=document.createElement('input'); yr.type='number'; yr.min=0; yr.max=50;
    yr.className='yrs'; yr.placeholder='0';
    var yl=document.createElement('span'); yl.className='yl'; yl.textContent=window.OB_YRS||'yrs';
    // "courses only" — familiar via tutorials/courses, no real project; disables the years input
    var crs=document.createElement('span'); crs.className='crs'; crs.textContent=window.OB_CRS||'courses';
    crs.title=window.OB_CRS; crs.onclick=function(e){e.stopPropagation();
      chip.classList.toggle('crs-on'); yr.disabled=chip.classList.contains('crs-on');
      if(chip.classList.contains('crs-on'))chip.classList.add('on');};
    chip.appendChild(lbl); chip.appendChild(yr); chip.appendChild(yl); chip.appendChild(crs);
    return chip;
  }
  async function pickOcc(o){
    f_occ.value=o.id; qs('#pickedocc').textContent='· '+o.label;
    var sk=await getJSON('/onboarding/api/skills?occupation_id='+o.id);
    var ess=qs('#skills-ess'), opt=qs('#skills-opt'); ess.innerHTML=''; opt.innerHTML='';
    var nopt=0;
    sk.forEach(function(s){
      if(s.essential){ ess.appendChild(makeChip(s, true)); }
      else { opt.appendChild(makeChip(s, false)); nopt++; }
    });
    qs('#opt-group').style.display = nopt ? '' : 'none';
    qs('#opt-n').textContent = nopt ? ('('+nopt+')') : '';
    opt.classList.add('hide'); qs('#opt-verb').textContent = window.OB_SHOW||'Show more';
    show(4);
  }
  qs('#opt-toggle').onclick=function(){
    var hidden=qs('#skills-opt').classList.toggle('hide');
    qs('#opt-verb').textContent = hidden ? (window.OB_SHOW||'Show more') : (window.OB_HIDE||'Hide');
  };

  // submit: build "Skill Ny" / "Skill (courses)" from selected chips
  qs('#obform').addEventListener('submit',function(e){
    if(!f_occ.value){e.preventDefault();show(2);return;}
    var parts=[];
    ob.querySelectorAll('.skills .skill.on').forEach(function(c){
      var lab=c.dataset.label;
      if(c.classList.contains('crs-on')){parts.push(lab+' (courses)');return;}
      var y=parseInt(c.querySelector('.yrs').value,10);
      parts.push(lab+(y>0?(' '+y+'y'):''));
    });
    qs('#f_skills').value=parts.join(', ');
  });

  // bulk years: one "total experience" value fills the years of every selected skill at once
  function bulkApply(){
    var y=parseInt(qs('#bulkyears').value,10);
    if(!(y>=0)) return;
    ob.querySelectorAll('.skills .skill.on').forEach(function(c){
      if(c.classList.contains('crs-on')) return;      // courses-only keeps its marker
      c.querySelector('.yrs').value=y;
    });
  }
  qs('#bulkapply').onclick=bulkApply;
  qs('#bulkyears').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();bulkApply();}});
})();
"""


@router.get("/onboarding", response_class=HTMLResponse)
def onboarding_form(request: Request, db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    lang = current_lang(request)
    return page(onboarding_card(lang=lang, db=db), u, title=t("ob.title", lang),
                lang=lang, switch_urls=SWITCH_URLS)


@router.post("/onboarding")
def onboarding_create(request: Request, occupation_id: str = Form(""),
                      skills_blob: str = Form(""), extra_skills: str = Form(""),
                      country: str = Form("Bulgaria"), location_pref: str = Form(""),
                      remote_pref: str = Form("remote"), relocate: str = Form(""),
                      languages: str = Form("Bulgarian, English"),
                      english_level: str = Form("B2"), db: Session = Depends(get_db)):
    u = current_user(request, db)
    if not u:
        return redirect("/login")
    occ = None
    if occupation_id.isdigit():
        occ = db.execute(select(Occupation).where(
            Occupation.id == int(occupation_id))).scalar_one_or_none()
    if occ is None:
        return redirect("/onboarding")
    lang = current_lang(request)
    # skills_blob is "Skill 5y, Skill2 3y, …" (years already inline); extra_skills is free text
    parts = [s.strip() for s in (skills_blob.split(",") + extra_skills.split(",")) if s.strip()]
    ordered, seen = [], set()
    for s in parts:
        key = s.split()[0].lower() if s.split() else s.lower()  # dedup on the skill name, not years
        if key not in seen:
            seen.add(key)
            ordered.append(s)
    labels = occ.labels or {}
    en_label = labels.get("en") or next(iter(labels.values()), "")
    p = Profile(
        user_id=u.id, name=(labels.get(lang) or en_label),
        target_roles=en_label,                           # matching/role_family are English-keyed
        skills=", ".join(ordered), languages=languages or "Bulgarian, English",
        english_level=english_level or "B2", country=country or "Bulgaria",
        location_pref=location_pref or "Sofia", remote_pref=remote_pref or "remote",
        relocate=bool(relocate), min_match=65)
    db.add(p); db.commit(); db.refresh(p)
    return redirect(f"/profiles/{p.id}")
