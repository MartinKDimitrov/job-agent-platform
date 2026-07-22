"""Lightweight i18n: a small translation catalog + language resolution.

No gettext/babel dependency — a plain dict keeps it cheap and modular (see LLM/cost ethos).
English is the default and the fallback; Bulgarian is the second language for the BG + remote-EU
market. Public pages use language-prefixed URLs (/ vs /bg) so hreflang works; logged-in screens
resolve via the `lang` cookie (the EN/BG switcher in the header) and Accept-Language.
"""
from fastapi import Request

LANGS = ["en", "bg"]
DEFAULT_LANG = "en"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "nav.dashboard": "Dashboard", "nav.documents": "Documents", "nav.sources": "Sources",
        "nav.account": "Account",
        "nav.logout": "Log out", "nav.login": "Sign in", "nav.register": "Register",
        "menu.pause": "I found a job — pause", "menu.resume": "Resume my search",
        "menu.settings": "AI key & settings", "menu.export": "Export my data",
        "menu.delete": "Delete account",
        "landing.title": "Job Agent — find jobs that match your skills",
        "landing.description": ("Describe your professional skills and get open positions scored "
                                "against your profile, with a direct apply link for each match."),
        "landing.h1": "Find jobs that match you",
        "landing.sub": "Create profiles, score openings against them, and apply directly.",
        "landing.get_started": "Get started", "landing.login": "Login",
        "login.title": "Login — Job Agent", "login.heading": "Login",
        "login.email": "Email", "login.password": "Password", "login.submit": "Login",
        "login.or": "Or", "auth.google": "Sign in with Google",
        "register.title": "Register — Job Agent", "register.heading": "Register",
        "register.name": "Name", "register.email": "Email", "register.password": "Password",
        "register.submit": "Create account",
        # ---- logged-in app (profile form) ----
        "form.name": 'Profile name (e.g. "Senior Android")',
        "form.target_roles": "Target roles (comma-separated)",
        "form.skills": "Skills (comma-separated)",
        "form.experience": "Experience (short)",
        "form.languages": "Languages", "form.english": "English level (CEFR)",
        "form.location": "Location preference", "form.remote": "Remote preference",
        "form.salary": "Salary expectation", "form.min_match": "Min match %",
        "form.save": "Save", "form.cancel": "Cancel", "form.fix": "Please fix:",
        "form.new_profile": "New profile", "form.edit_profile": "Edit profile",
        "form.delete_head": "Delete this profile",
        "form.delete_note": "Removes the profile and its matches. This cannot be undone.",
        "form.delete_btn": "Delete profile",
        "form.delete_confirm": "Delete this profile and its matches? This cannot be undone.",
        "opt.remote": "remote", "opt.hybrid": "hybrid", "opt.onsite": "onsite", "opt.any": "any",
        "err.name_required": "Profile name is required.",
        "err.name_long": "Profile name is too long (max 255 characters).",
        "err.min_match": "Min match must be a whole number between 0 and 100.",
        "err.english": "English level must be one of A2, B1, B2, C1, C2.",
        "err.remote": "Remote preference must be remote, hybrid, onsite or any.",
        "err.salary_long": "Salary expectation is too long (max 64 characters).",
        # ---- logged-in app (feed / gaps / control strip) ----
        "gaps.covered": "covered", "gaps.to_check": "to check",
        "gaps.tap": "tap for details", "gaps.you_cover": "You cover",
        "gaps.not_in_profile": "Not in your profile",
        "gaps.advantage": "Considered an advantage",
        "gaps.honest": ("Be honest about these when applying — or add them to your profile "
                        "if you have them."),
        "app.matches_ge": "Matches ≥", "app.min": "min", "app.apply_thresh": "Apply",
        "app.edit": "Edit", "app.edit_title": "Edit this profile",
        "app.search_now": "Search now", "app.new_tab": "+ New",
        "app.searching": "⏳ Searching…", "app.generating": "⏳ Generating…",
        "app.gen_failed": "Generation failed:",
        "app.search_done": ("Search complete — fetched {fetched} postings, {new} new, "
                            "{filt}<b>{found} match(es)</b> above your {min}% threshold."),
        "app.filtered": "{n} filtered out (seniority/location), ",
        "app.empty_head": "No matches above threshold yet",
        "app.empty_body": "Run a search, lower the threshold, or add a posting manually below.",
        "app.your_docs": "Your documents", "app.apply": "Apply",
        "app.cv": "CV", "app.letter": "Letter",
        "app.cv_title": "Generate a tailored CV (uses your AI key)",
        "app.letter_title": "Generate a cover letter (uses your AI key)",
        "app.add_posting": "Add a posting manually (advanced)",
        "app.job_url": "Job URL", "app.apply_url": "Apply URL (direct, if different)",
        "app.title": "Title", "app.company": "Company", "app.location": "Location",
        "app.description": "Description / requirements (paste the JD)",
        "app.score_it": "Score it", "app.not_found": "Not found.",
    },
    "bg": {
        "nav.dashboard": "Табло", "nav.documents": "Документи", "nav.sources": "Източници",
        "nav.account": "Профил",
        "nav.logout": "Изход", "nav.login": "Вход", "nav.register": "Регистрация",
        "menu.pause": "Намерих работа — пауза", "menu.resume": "Продължи търсенето",
        "menu.settings": "AI ключ и настройки", "menu.export": "Изтегли данните ми",
        "menu.delete": "Изтрий акаунта",
        "landing.title": "Job Agent — работа, която пасва на уменията ти",
        "landing.description": ("Опиши професионалните си умения и получи отворени позиции, "
                                "оценени спрямо профила ти, с директен линк за кандидатстване "
                                "за всяко съвпадение."),
        "landing.h1": "Намери работа, която ти пасва",
        "landing.sub": "Създай профили, оцени обяви спрямо тях и кандидатствай директно.",
        "landing.get_started": "Започни", "landing.login": "Вход",
        "login.title": "Вход — Job Agent", "login.heading": "Вход",
        "login.email": "Имейл", "login.password": "Парола", "login.submit": "Вход",
        "login.or": "Или", "auth.google": "Влез с Google",
        "register.title": "Регистрация — Job Agent", "register.heading": "Регистрация",
        "register.name": "Име", "register.email": "Имейл", "register.password": "Парола",
        "register.submit": "Създай акаунт",
        # ---- logged-in app (profile form) ----
        "form.name": 'Име на профила (напр. "Senior Android")',
        "form.target_roles": "Търсени позиции (разделени със запетая)",
        "form.skills": "Умения (разделени със запетая)",
        "form.experience": "Опит (накратко)",
        "form.languages": "Езици", "form.english": "Ниво на английски (CEFR)",
        "form.location": "Предпочитана локация", "form.remote": "Начин на работа",
        "form.salary": "Очаквано възнаграждение", "form.min_match": "Мин. съвпадение %",
        "form.save": "Запази", "form.cancel": "Отказ", "form.fix": "Моля, поправете:",
        "form.new_profile": "Нов профил", "form.edit_profile": "Редакция на профил",
        "form.delete_head": "Изтриване на профила",
        "form.delete_note": "Премахва профила и съвпаденията му. Действието е необратимо.",
        "form.delete_btn": "Изтрий профила",
        "form.delete_confirm": "Да изтрия ли профила и съвпаденията му? Действието е необратимо.",
        "opt.remote": "дистанционно", "opt.hybrid": "хибридно",
        "opt.onsite": "на място", "opt.any": "без значение",
        "err.name_required": "Името на профила е задължително.",
        "err.name_long": "Името на профила е твърде дълго (макс. 255 знака).",
        "err.min_match": "Мин. съвпадение трябва да е цяло число между 0 и 100.",
        "err.english": "Нивото на английски трябва да е едно от A2, B1, B2, C1, C2.",
        "err.remote": "Начинът на работа трябва да е дистанционно, хибридно, на място или без значение.",
        "err.salary_long": "Очакваното възнаграждение е твърде дълго (макс. 64 знака).",
        # ---- logged-in app (feed / gaps / control strip) ----
        "gaps.covered": "покрити", "gaps.to_check": "за проверка",
        "gaps.tap": "виж детайли", "gaps.you_cover": "Покриваш",
        "gaps.not_in_profile": "Не е в профила ти",
        "gaps.advantage": "Считат се за предимство",
        "gaps.honest": ("Бъди честен за тези при кандидатстване — или ги добави в профила си, "
                        "ако ги имаш."),
        "app.matches_ge": "Съвпадения ≥", "app.min": "мин.", "app.apply_thresh": "Приложи",
        "app.edit": "Редакция", "app.edit_title": "Редактирай този профил",
        "app.search_now": "Търси сега", "app.new_tab": "+ Нов",
        "app.searching": "⏳ Търсене…", "app.generating": "⏳ Генериране…",
        "app.gen_failed": "Генерирането се провали:",
        "app.search_done": ("Търсенето приключи — изтеглени {fetched} обяви, {new} нови, "
                            "{filt}<b>{found} съвпадение(я)</b> над прага ти от {min}%."),
        "app.filtered": "{n} отпаднали (ниво/локация), ",
        "app.empty_head": "Все още няма съвпадения над прага",
        "app.empty_body": "Пусни търсене, намали прага или добави обява ръчно по-долу.",
        "app.your_docs": "Твоите документи", "app.apply": "Кандидатствай",
        "app.cv": "CV", "app.letter": "Писмо",
        "app.cv_title": "Генерирай персонализирано CV (използва твоя AI ключ)",
        "app.letter_title": "Генерирай мотивационно писмо (използва твоя AI ключ)",
        "app.add_posting": "Добави обява ръчно (за напреднали)",
        "app.job_url": "Линк към обявата", "app.apply_url": "Линк за кандидатстване (ако е различен)",
        "app.title": "Заглавие", "app.company": "Компания", "app.location": "Локация",
        "app.description": "Описание / изисквания (постави обявата)",
        "app.score_it": "Оцени я", "app.not_found": "Не е намерено.",
    },
}


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Translate `key` into `lang`, falling back to the default language, then the key itself."""
    if lang not in LANGS:
        lang = DEFAULT_LANG
    val = TRANSLATIONS.get(lang, {}).get(key)
    if val is not None:
        return val
    return TRANSLATIONS.get(DEFAULT_LANG, {}).get(key, key)


def _parse_accept_language(header: str) -> str | None:
    """Return the first supported language from an Accept-Language header, by q-weight."""
    if not header:
        return None
    weighted = []
    for item in header.split(","):
        item = item.strip()
        if not item:
            continue
        code, _, q = item.partition(";q=")
        code = code.strip().lower().split("-")[0]
        try:
            qv = float(q) if q else 1.0
        except ValueError:
            qv = 1.0
        weighted.append((qv, code))
    for _, code in sorted(weighted, key=lambda x: x[0], reverse=True):
        if code in LANGS:
            return code
    return None


def current_lang(request: Request, explicit: str | None = None) -> str:
    """Resolve the active language: explicit (URL) → cookie → Accept-Language → default."""
    if explicit in LANGS:
        return explicit
    cookie = request.cookies.get("lang")
    if cookie in LANGS:
        return cookie
    return _parse_accept_language(request.headers.get("accept-language", "")) or DEFAULT_LANG
