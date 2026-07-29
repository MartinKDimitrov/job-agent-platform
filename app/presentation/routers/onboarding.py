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


# Language picker options: (stored EN value, BG label, EN label). Stored value is the English name
# so the matcher (English-keyed) reads it consistently; the UI shows the localized label.
_LANGUAGES = [
    ("Bulgarian", "Български", "Bulgarian"), ("English", "Английски", "English"),
    ("German", "Немски", "German"), ("French", "Френски", "French"),
    ("Spanish", "Испански", "Spanish"), ("Italian", "Италиански", "Italian"),
    ("Dutch", "Нидерландски", "Dutch"), ("Polish", "Полски", "Polish"),
    ("Romanian", "Румънски", "Romanian"), ("Greek", "Гръцки", "Greek"),
    ("Swedish", "Шведски", "Swedish"), ("Portuguese", "Португалски", "Portuguese"),
    ("Czech", "Чешки", "Czech"), ("Hungarian", "Унгарски", "Hungarian"),
    ("Croatian", "Хърватски", "Croatian"), ("Turkish", "Турски", "Turkish"),
    ("Russian", "Руски", "Russian"), ("Ukrainian", "Украински", "Ukrainian"),
    ("Arabic", "Арабски", "Arabic"), ("Chinese", "Китайски", "Chinese"),
]


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
    langs_json = json.dumps([{"v": v, "l": (bg if lang == "bg" else en)}
                             for v, bg, en in _LANGUAGES], ensure_ascii=False)
    return f"""
<div class='card ob' id='ob'>
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
        <label>{escape(S['country'])}<select name='country' id='f_country' class='cselect'>{country_opts}</select></label>
        <label class='ac-wrap'>{escape(S['city'])}
          <input name='location_pref' id='f_city' autocomplete='off' value='Sofia'
                 placeholder='{escape(S['city_ph'])}'>
          <div id='citylist' class='ac'></div></label>
        <label>{escape(S['work'])}<select name='remote_pref' class='cselect'>{remote_opts}</select></label>
        <label>{escape(S['english'])}<select name='english_level' class='cselect'>{cefr}</select></label>
        <div class='wide lang-picker'>
          <label>{escape(S['langs'])}</label>
          <div class='lp-search-wrap'>
            <input type='search' id='lang-search' placeholder='{escape(S['lang_ph'])}' autocomplete='off'>
            <div id='lang-sugg' class='lp-sugg hide'></div>
          </div>
          <div id='lang-chips' class='lp-chips'></div>
          <input type='hidden' name='languages' id='f_languages'>
        </div>
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
      <p class='small'>{escape(S['s3_sub'])}</p>
      <div class='field-box'><span class='fb-ic' id='fb-ic'></span>
        <div><div class='fb-label'>{escape(S['field_label'])}</div>
          <div class='fb-name' id='fb-name'></div></div></div>
      <input type='search' id='occsearch' placeholder='{escape(S['search'])}' autocomplete='off'>
      <div class='groups-h' id='groups-h'>{escape(S['groups_h'])}</div>
      <div id='subcats' class='acc'></div>
      <div id='searchres' class='searchres'></div>
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
      <div class='ob-nav s4-nav'><a href='#' class='back' data-back='3'>{escape(S['back'])}</a>
        <span class='s4-right'><span id='sk-count' class='sk-count small'></span>
        <button class='btn big' id='create'>{escape(S['create'])}</button></span></div>
    </section>
  </form>
</div>
{_ob_style()}
<script>window.OB_YRS={json.dumps(S['yrs'])};window.OB_CRS={json.dumps(S['courses'])};
window.OB_SHOW={json.dumps(S['show_more'])};window.OB_HIDE={json.dumps(S['hide_more'])};
window.OB_NPROF={json.dumps(S['n_prof'])};window.OB_OCCIN={json.dumps(S['occ_in'])};window.OB_NOMATCH={json.dumps(S['no_match'])};
window.OB_LANGS={langs_json};window.OB_LANGLVL={json.dumps(S['lang_lvl'])};window.OB_LANGNONE={json.dumps(S['lang_none'])};
window.OB_SKCOUNT={json.dumps(S['s4_count'])};
{_ob_script(lang)}</script>"""


def _step_strings(lang: str) -> dict:
    L = lambda bg, en: _L(lang, bg, en)  # noqa: E731
    return {
        "s1": L("За теб", "About you"), "s2": L("Област", "Field"),
        "s3": L("Професия", "Occupation"), "s4": L("Умения", "Skills"),
        "s1_h": L("Първо накратко за теб", "First, a bit about you"),
        "s2_h": L("В коя област търсиш работа?", "Which field are you in?"),
        "s3_h": L("Коя е вашата професия?", "What's your occupation?"),
        "s3_sub": L("Изберете група професии, после конкретната позиция под нея.",
                    "Pick an occupation group, then the specific role under it."),
        "field_label": L("Сфера", "Field"),
        "groups_h": L("Групи професии", "Occupation groups"),
        "occ_in": L("Професии в", "Occupations in"),
        "n_prof": L("професии", "occupations"),
        "no_match": L("Няма съвпадения за", "No matches for"),
        "lang_ph": L("Търсете език и го добавете…", "Search a language and add it…"),
        "lang_none": L("Още няма добавени езици.", "No languages added yet."),
        "lang_lvl": L("Ниво", "Level"),
        "lang_sub": L("Добавете езиците, които владеете, и посочете ниво по желание.",
                      "Add the languages you speak, optionally with a level."),
        "s4_h": L("Твоите квалификации", "Your qualifications"),
        "s4_count": L("избрани умения", "selected skills"),
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
    #ob .ob-steps{display:flex;gap:8px;margin:4px 0 26px;font-size:13.5px}
    #ob .st{flex:1;text-align:center;padding:7px 14px;border-radius:999px;background:transparent;
      color:var(--muted);font-weight:600;border:1px solid var(--line,#e5e8ee)}
    #ob .st.done{background:var(--green-soft);color:var(--navy);border-color:transparent}
    #ob .st.on{background:var(--navy);color:var(--on-accent);border-color:transparent}
    #ob .st.nav{cursor:pointer}
    #ob .st.nav:hover{border-color:var(--navy);color:var(--navy)}
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
    #ob .ac{position:absolute;left:0;right:0;top:100%;z-index:20;background:var(--card);
      border:1px solid var(--line,#e5e8ee);border-radius:8px;margin-top:2px;max-height:220px;
      overflow:auto;display:none;box-shadow:0 6px 20px rgba(0,0,0,.08)}
    #ob .ac.show{display:block}
    #ob .ac div{padding:8px 12px;cursor:pointer;font-size:14px}
    #ob .ac div:hover,#ob .ac div.sel{background:var(--line,#eef1f6)}
    /* language picker */
    #ob .lang-picker .lp-sub{margin:2px 0 10px}
    #ob .lp-search-wrap{position:relative}
    #ob .lp-sugg{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:30;max-height:220px;
      overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px;
      box-shadow:var(--shadow-md,0 10px 28px rgba(0,0,0,.14))}
    #ob .lp-sugg.hide{display:none}
    #ob .lp-sug{display:block;width:100%;padding:9px 12px;border:0;border-radius:8px;background:none;
      cursor:pointer;text-align:left;font-size:14px;color:var(--ink)}
    #ob .lp-sug:hover{background:var(--gray-soft)}
    #ob .lp-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
    #ob .lp-none{color:var(--muted);margin:6px 0 0}
    #ob .lp-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 6px 5px 12px;
      border:1px solid var(--navy);background:var(--green-soft);border-radius:12px}
    #ob .lp-name{font-size:13.5px;font-weight:600;color:var(--ink)}
    #ob .lp-lvl{width:auto;min-height:30px;padding:4px 8px;font-size:12.5px;border-radius:8px;
      border:1px solid var(--line-strong);background:var(--card);color:var(--ink)}
    #ob .lp-rm{width:28px;height:28px;padding:0;border:0;border-radius:8px;background:none;cursor:pointer;
      color:var(--muted);font-size:18px;line-height:1}
    #ob .lp-rm:hover{background:var(--card);color:var(--ink)}
    /* custom dropdown (opens below, green check) */
    #ob .csw{position:relative}
    #ob .cs-btn{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;
      min-height:44px;padding:10px 12px;border:1px solid var(--line-strong);border-radius:9px;
      background:var(--card);color:var(--ink);font-size:15px;cursor:pointer;text-align:left}
    #ob .csw.open .cs-btn{border-color:var(--navy);box-shadow:0 0 0 3px var(--green-soft)}
    #ob .cs-lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #ob .cs-chev{color:var(--muted);flex-shrink:0;transition:transform .15s ease}
    #ob .csw.open .cs-chev{transform:rotate(180deg)}
    #ob .cs-panel{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:30;max-height:260px;
      overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px;
      box-shadow:var(--shadow-md,0 10px 28px rgba(0,0,0,.14))}
    #ob .cs-panel.hide{display:none}
    #ob .cs-opt{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;
      padding:10px 12px;border:0;border-radius:8px;background:none;cursor:pointer;text-align:left;
      font-size:14px;color:var(--ink)}
    #ob .cs-opt:hover{background:var(--gray-soft)}
    #ob .cs-opt.sel{background:var(--green-soft);color:var(--teal-ink);font-weight:600}
    #ob .cs-ck{color:var(--navy);opacity:0;flex-shrink:0}
    #ob .cs-opt.sel .cs-ck{opacity:1}
    /* compact variant when the custom dropdown sits inside a language chip */
    #ob .lp-chip .csw{flex-shrink:0}
    #ob .lp-chip .cs-btn{min-height:30px;width:auto;padding:4px 8px;font-size:12.5px;
      border-radius:8px;gap:6px}
    #ob .lp-chip .csw.open .cs-btn{box-shadow:0 0 0 2px var(--green-soft)}
    #ob .lp-chip .cs-panel{left:0;right:auto;min-width:118px}
    #ob .lp-chip .cs-opt{padding:7px 10px;font-size:13px}
    #ob .cats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:6px 0}
    @media(max-width:640px){#ob .cats{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media(max-width:420px){#ob .cats{grid-template-columns:minmax(0,1fr)}}
    #ob .cat{border:1px solid var(--line);background:var(--card);border-radius:12px;
      padding:12px 16px;cursor:pointer;font-size:15px;text-align:left;
      display:flex;align-items:center;gap:10px;min-width:0;color:var(--ink)}
    #ob .cat .ic{font-size:20px}
    #ob .cat:hover{border-color:var(--navy)}
    #ob #occsearch{width:100%;margin:6px 0 4px;padding:10px 12px}
    /* step 3 — field box (parent group) + accordion of occupation groups */
    #ob .field-box{display:flex;align-items:center;gap:12px;margin:6px 0 14px;padding:12px 16px;
      background:var(--green-soft);border:1px solid var(--navy);border-radius:12px}
    #ob .fb-ic{font-size:22px}
    #ob .fb-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
    #ob .fb-name{font-size:14px;font-weight:700;color:var(--ink)}
    #ob .fb-name .chev{color:var(--muted);font-weight:400}
    #ob .groups-h{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
      color:var(--muted);margin:16px 0 8px}
    #ob .acc{display:flex;flex-direction:column;gap:10px}
    #ob .acc-item{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card)}
    #ob .acc-item.open{border-color:var(--navy)}
    #ob .acc-head{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;
      padding:13px 16px;background:none;border:0;cursor:pointer;text-align:left;color:var(--ink)}
    #ob .acc-head:hover{background:var(--gray-soft)}
    #ob .acc-item.open .acc-head{background:var(--navy);color:var(--on-accent)}
    #ob .ah-title{display:block;font-size:14px;font-weight:700}
    #ob .ah-count{display:block;font-size:12px;color:var(--muted)}
    #ob .acc-item.open .ah-count{color:var(--on-accent);opacity:.85}
    #ob .acc-item.open .ah-chev{transform:rotate(90deg)}
    #ob .ah-chev{transition:transform .15s ease;flex-shrink:0}
    #ob .acc-body{border-top:1px solid var(--line);padding:8px 14px 10px 22px}
    #ob .acc-body.hide{display:none}
    #ob .acc-body-h{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
      color:var(--muted);padding:4px 6px}
    #ob .occ-list{display:flex;flex-direction:column;border-left:2px solid var(--green-soft);padding-left:6px}
    #ob .searchres .occ-list{border-left:0;padding-left:0}
    #ob .occ{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;
      padding:10px 12px;background:none;border:0;border-radius:9px;cursor:pointer;text-align:left;
      font-size:14px;color:var(--ink)}
    #ob .occ:hover{background:var(--gray-soft)}
    #ob .occ .oa{color:var(--muted);flex-shrink:0}
    #ob .no-match{padding:22px;text-align:center;color:var(--muted);border:1px solid var(--line);
      border-radius:12px;background:var(--card)}
    #ob .bulk-years{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:6px 0 14px;
      padding:12px 14px;background:var(--green-soft);border:1px solid var(--line,#dbe3ea);
      border-radius:10px}
    #ob .bulk-years label{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:600}
    #ob .bulk-years input{width:64px;padding:5px 8px;border-radius:7px;
      border:1px solid var(--line,#c9cfdb)}
    #ob .bulk-years .bh{color:var(--muted,#778);font-weight:400;flex:1 1 160px}
    #ob .sk-group{margin-bottom:14px}
    #ob .sk-head{font-size:13px;font-weight:600;color:var(--ink,#222);margin:0 0 8px}
    #ob .sk-sub{font-weight:400;color:var(--muted,#889);font-size:12px}
    #ob .opt-toggle{background:none;border:1px dashed var(--line,#c9cfdb);border-radius:8px;
      padding:8px 12px;cursor:pointer;font-size:13px;color:var(--teal-ink);font-weight:600}
    #ob .opt-toggle .opt-n{color:var(--muted,#889);font-weight:400;margin-left:2px}
    #ob #skills-opt{margin-top:10px}
    #ob #skills-opt.hide{display:none}
    #ob .skills{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}
    @media(max-width:560px){#ob .skills{grid-template-columns:minmax(0,1fr)}}
    #ob .skill{display:flex;align-items:center;gap:10px;cursor:pointer;min-width:0;
      border:1px solid var(--line,#e5e8ee);border-radius:12px;padding:11px 13px;
      font-size:14px;background:var(--card,#fff);transition:border-color .12s,background .12s}
    #ob .skill:hover{border-color:var(--navy)}
    #ob .skill.on{border-color:var(--navy);background:var(--green-soft)}
    #ob .skill .sk-cb{flex:none;width:20px;height:20px;border-radius:6px;
      border:1.5px solid var(--line,#cdd3de);background:var(--card,#fff);
      display:flex;align-items:center;justify-content:center;transition:all .12s}
    #ob .skill .sk-cb::after{content:'✓';color:#fff;font-size:13px;font-weight:700;
      line-height:1;opacity:0;transform:scale(.6);transition:all .12s}
    #ob .skill.on .sk-cb{background:var(--navy);border-color:var(--navy)}
    #ob .skill.on .sk-cb::after{opacity:1;transform:scale(1)}
    #ob .skill .sk-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #ob .skill.ess .sk-name::after{content:' •';color:var(--navy)}
    #ob .skill .yrs{width:48px;padding:4px 6px;font-size:13px;border-radius:8px;
      border:1px solid var(--line,#e5e8ee);display:none;background:var(--card,#fff)}
    #ob .skill.on .yrs{display:inline-block}
    #ob .skill .yl{font-size:12px;color:var(--muted,#889);display:none}
    #ob .skill.on .yl{display:inline}
    #ob .skill .crs{display:none;font-size:11px;padding:3px 9px;border-radius:10px;cursor:pointer;
      border:1px dashed var(--line,#c9cfdb);color:var(--muted,#778);white-space:nowrap}
    #ob .skill.on .crs{display:inline}
    #ob .skill.crs-on .crs{border-style:solid;border-color:var(--navy);
      color:var(--navy);background:var(--green-soft)}
    #ob .skill.crs-on .yrs,#ob .skill.crs-on .yl{opacity:.35}
    #ob .s4-nav{display:flex;align-items:center;justify-content:space-between}
    #ob .s4-nav .s4-right{display:flex;align-items:center;gap:14px}
    #ob .sk-count{color:var(--muted,#889);font-size:13px}
    #ob .skill.crs-on .crs{background:var(--navy);color:#fff;border-style:solid}
    #ob .skill.crs-on .yrs,#ob .skill.crs-on .yl{opacity:.35}
    #ob .ob-nav{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px}
    #ob .ob-nav .back{color:var(--muted,#667);font-size:14px}
    </style>"""


def _ob_script(lang: str) -> str:
    return r"""
(function(){
  var ob=document.getElementById('ob'); if(!ob) return;
  var qs=function(s){return ob.querySelector(s);};
  var reached=1;  // furthest step the user has unlocked — steps up to here are clickable
  function show(n){
    reached=Math.max(reached,n);
    ob.querySelectorAll('.ob-panel').forEach(function(p){p.classList.toggle('hide',p.dataset.s!=String(n));});
    ob.querySelectorAll('.st').forEach(function(s){var i=Number(s.dataset.s);
      s.classList.toggle('on',i===n); s.classList.toggle('done',i<n);
      s.classList.toggle('nav',i<=reached && i!==n);});
  }
  // clickable stepper: jump to any step already reached
  ob.querySelectorAll('.st').forEach(function(s){s.addEventListener('click',function(){
    var i=Number(s.dataset.s); if(i<=reached) show(i);});});
  function debounce(fn,ms){var t;return function(){var a=arguments,c=this;clearTimeout(t);
    t=setTimeout(function(){fn.apply(c,a);},ms);};}
  async function getJSON(u){var r=await fetch(u);return r.json();}

  // custom dropdown — replaces native <select class=cselect>: opens BELOW, green check on selected,
  // keeps the native select (hidden) for form submission + change events (country->city dependency)
  function enhanceSelect(sel){
    var wrap=document.createElement('div'); wrap.className='csw';
    var btn=document.createElement('button'); btn.type='button'; btn.className='cs-btn';
    var lbl=document.createElement('span'); lbl.className='cs-lbl';
    var chev=document.createElement('span'); chev.className='cs-chev'; chev.textContent='▾';
    btn.appendChild(lbl); btn.appendChild(chev);
    var panel=document.createElement('div'); panel.className='cs-panel hide';
    function sync(){var o=sel.options[sel.selectedIndex]; lbl.textContent=o?o.text:'';
      [].forEach.call(panel.children,function(it,i){it.classList.toggle('sel',i===sel.selectedIndex);});}
    [].forEach.call(sel.options,function(o,i){
      var it=document.createElement('button'); it.type='button'; it.className='cs-opt';
      var t=document.createElement('span'); t.textContent=o.text;
      var ck=document.createElement('span'); ck.className='cs-ck'; ck.textContent='✓';
      it.appendChild(t); it.appendChild(ck);
      it.onclick=function(){sel.selectedIndex=i; sync();
        sel.dispatchEvent(new Event('change',{bubbles:true})); panel.classList.add('hide'); wrap.classList.remove('open');};
      panel.appendChild(it);
    });
    btn.onclick=function(){var h=panel.classList.toggle('hide'); wrap.classList.toggle('open',!h);};
    document.addEventListener('click',function(e){if(!wrap.contains(e.target)){panel.classList.add('hide');wrap.classList.remove('open');}});
    sel.style.display='none'; sel.parentNode.insertBefore(wrap,sel);
    wrap.appendChild(btn); wrap.appendChild(panel); wrap.appendChild(sel); sync();
  }
  ob.querySelectorAll('select.cselect').forEach(enhanceSelect);

  // language picker: search + add as chips with optional CEFR level -> hidden #f_languages
  (function(){
    var search=qs('#lang-search'), sugg=qs('#lang-sugg'), chipbox=qs('#lang-chips'), hidden=qs('#f_languages');
    if(!search) return;
    var chosen=[], LEVELS=['','A1','A2','B1','B2','C1','C2'];
    function serialize(){hidden.value=chosen.map(function(c){return c.level?(c.v+' '+c.level):c.v;}).join(', ');}
    function render(){
      chipbox.innerHTML='';
      if(!chosen.length){var e=document.createElement('p');e.className='small lp-none';e.textContent=window.OB_LANGNONE||'';chipbox.appendChild(e);serialize();return;}
      chosen.forEach(function(c,idx){
        var chip=document.createElement('span'); chip.className='lp-chip';
        var nm=document.createElement('span'); nm.className='lp-name'; nm.textContent=c.l;
        var sel=document.createElement('select'); sel.className='lp-lvl';
        LEVELS.forEach(function(lv){var o=document.createElement('option');o.value=lv;o.textContent=lv||(window.OB_LANGLVL||'—');if(lv===c.level)o.selected=true;sel.appendChild(o);});
        sel.onchange=function(){c.level=sel.value;serialize();};
        var rm=document.createElement('button'); rm.type='button'; rm.className='lp-rm'; rm.textContent='×';
        rm.setAttribute('aria-label','×'); rm.onclick=function(){chosen.splice(idx,1);render();};
        chip.appendChild(nm); chip.appendChild(sel); enhanceSelect(sel); chip.appendChild(rm); chipbox.appendChild(chip);
      });
      serialize();
    }
    function suggest(){
      var q=search.value.trim().toLowerCase(), taken={}; chosen.forEach(function(c){taken[c.v]=1;});
      var res=(window.OB_LANGS||[]).filter(function(L){return !taken[L.v]&&(!q||L.l.toLowerCase().indexOf(q)>=0);}).slice(0,8);
      sugg.innerHTML='';
      if(!res.length){sugg.classList.add('hide');return;}
      res.forEach(function(L){var b=document.createElement('button');b.type='button';b.className='lp-sug';b.textContent=L.l;
        b.onmousedown=function(e){e.preventDefault();};b.onclick=function(){chosen.push({v:L.v,l:L.l,level:''});search.value='';sugg.classList.add('hide');render();};
        sugg.appendChild(b);});
      sugg.classList.remove('hide');
    }
    search.addEventListener('focus',suggest); search.addEventListener('input',suggest);
    document.addEventListener('click',function(e){if(!sugg.contains(e.target)&&e.target!==search)sugg.classList.add('hide');});
    ['Bulgarian','English'].forEach(function(v){var L=(window.OB_LANGS||[]).find(function(x){return x.v===v;});if(L)chosen.push({v:L.v,l:L.l,level:''});});
    render();
  })();

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

  // category -> field box + accordion of occupation GROUPS -> nested occupations
  var f_occ=qs('#f_occ');
  function occRow(o){
    var b=document.createElement('button'); b.type='button'; b.className='occ';
    var l=document.createElement('span'); l.className='ol'; l.textContent=o.label; l.title=o.label;
    var a=document.createElement('span'); a.className='oa'; a.textContent='→';
    b.appendChild(l); b.appendChild(a); b.onclick=function(){pickOcc(o);}; return b;
  }
  function occList(list){var ul=document.createElement('div'); ul.className='occ-list';
    list.forEach(function(o){ul.appendChild(occRow(o));}); return ul;}
  ob.querySelectorAll('.cat').forEach(function(b){b.onclick=async function(){
    show(3); qs('#occsearch').value='';
    var ic=(b.querySelector('.ic')||{}).textContent||'';
    qs('#fb-ic').textContent=ic;
    qs('#fb-name').innerHTML=''; var nm=document.createElement('span');
    nm.textContent=b.textContent.replace(ic,'').trim();
    var cv=document.createElement('span'); cv.className='chev'; cv.textContent=' ›';
    qs('#fb-name').appendChild(nm); qs('#fb-name').appendChild(cv);
    var sr=qs('#searchres'); sr.innerHTML=''; sr.classList.remove('show'); qs('#groups-h').style.display='';
    var data=await getJSON('/onboarding/api/subcats?vertical='+encodeURIComponent(b.dataset.v));
    var box=qs('#subcats'); box.innerHTML=''; box.style.display='';
    data.forEach(function(g){
      var item=document.createElement('div'); item.className='acc-item';
      var head=document.createElement('button'); head.type='button'; head.className='acc-head';
      var lwrap=document.createElement('span'); lwrap.className='ah-l';
      var ti=document.createElement('span'); ti.className='ah-title'; ti.textContent=g.label;
      var cn=document.createElement('span'); cn.className='ah-count'; cn.textContent=g.count+' '+(window.OB_NPROF||'');
      lwrap.appendChild(ti); lwrap.appendChild(cn);
      var chev=document.createElement('span'); chev.className='ah-chev'; chev.textContent='▸';
      head.appendChild(lwrap); head.appendChild(chev);
      var body=document.createElement('div'); body.className='acc-body hide';
      head.onclick=async function(){
        var open=item.classList.toggle('open'); body.classList.toggle('hide',!open);
        if(open && !body.dataset.loaded){
          body.dataset.loaded='1';
          var occs=await getJSON('/onboarding/api/occupations?isco='+encodeURIComponent(g.isco_code));
          body.appendChild(occList(occs));
        }
      };
      item.appendChild(head); item.appendChild(body); box.appendChild(item);
    });
  };});
  // search -> flat results (hides the accordion)
  qs('#occsearch').addEventListener('input',debounce(async function(e){
    var q=e.target.value.trim(); var box=qs('#subcats'), gh=qs('#groups-h'), sr=qs('#searchres');
    if(q.length<2){box.style.display='';gh.style.display='';sr.innerHTML='';sr.classList.remove('show');return;}
    box.style.display='none'; gh.style.display='none';
    var res=await getJSON('/onboarding/api/search?q='+encodeURIComponent(q));
    sr.innerHTML=''; sr.classList.add('show');
    if(!res.length){var nm=document.createElement('div');nm.className='no-match';
      nm.textContent=(window.OB_NOMATCH||'')+' „'+q+'"';sr.appendChild(nm);return;}
    sr.appendChild(occList(res));
  },220));
  qs('#occsearch').addEventListener('keydown',function(e){if(e.key==='Enter')e.preventDefault();});

  function makeChip(s, selected){
    var chip=document.createElement('div'); chip.className='skill'+(selected?' on':'');
    chip.dataset.label=s.label;
    var cb=document.createElement('span'); cb.className='sk-cb';
    var nm=document.createElement('span'); nm.className='sk-name'; nm.textContent=s.label; nm.title=s.label;
    var yr=document.createElement('input'); yr.type='number'; yr.min=0; yr.max=50;
    yr.className='yrs'; yr.placeholder='0';
    var yl=document.createElement('span'); yl.className='yl'; yl.textContent=window.OB_YRS||'yrs';
    // "courses only" — familiar via tutorials/courses, no real project; disables the years input
    var crs=document.createElement('span'); crs.className='crs'; crs.textContent=window.OB_CRS||'courses';
    crs.title=window.OB_CRS; crs.onclick=function(e){e.stopPropagation();
      chip.classList.toggle('crs-on'); yr.disabled=chip.classList.contains('crs-on');
      if(chip.classList.contains('crs-on'))chip.classList.add('on'); updateCount();};
    yr.onclick=function(e){e.stopPropagation();};
    chip.onclick=function(e){if(e.target===yr||e.target===crs)return; chip.classList.toggle('on'); updateCount();};
    chip.appendChild(cb); chip.appendChild(nm); chip.appendChild(yr); chip.appendChild(yl); chip.appendChild(crs);
    return chip;
  }
  function updateCount(){var n=ob.querySelectorAll('.skills .skill.on').length;
    var el=qs('#sk-count'); if(el)el.textContent=n+' '+(window.OB_SKCOUNT||'');}
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
    updateCount(); show(4);
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
