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
        "form.country": "Country you live in",
        "form.relocate": "I'm willing to relocate abroad",
        "form.relocate_hint": ("When off, positions tied to another country (including "
                               "\"remote\" ones that require living there) are hidden."),
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
        "gaps.verified": "AI-checked",
        "gaps.honest": ("Be honest about these when applying — or add them to your profile "
                        "if you have them."),
        "app.matches_ge": "Matches ≥", "app.min": "min", "app.apply_thresh": "Apply",
        "app.edit": "Edit", "app.edit_title": "Edit this profile",
        "app.search_now": "Search now", "app.new_tab": "+ New",
        "app.searching": "⏳ Searching…", "app.generating": "⏳ Generating…",
        "app.gen_failed": "Generation failed:",
        "app.search_done": ("Search complete — searched {pool} tracked postings, "
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
        # ---- documents ----
        "docs.kind_cv": "CV", "docs.kind_letter": "Cover letter",
        "docs.my": "My documents", "docs.document": "Document", "docs.job": "Job",
        "docs.created": "Created", "docs.removed": "(posting removed)",
        "docs.none": "No documents yet — generate one from a match.",
        "docs.for": "For:",
        "docs.review_word": "Review and edit before using",
        "docs.review_rest": ("AI output is a draft, you own the final text. Edit below and "
                             "save; the PDF always uses your latest text."),
        "docs.saved_word": "Saved.", "docs.saved_rest": "The PDF uses your edited text.",
        "docs.save": "Save changes", "docs.download": "⬇ Download PDF",
        "docs.regen_in": "Regenerate in {lang}", "docs.other_for": "{kind} for this job",
        # ---- account / settings ----
        "acct.heading": "Account", "acct.joined": "joined",
        "acct.profiles": "{n} search profile(s).",
        "acct.export": "Export my data (JSON)",
        "acct.status_head": "Job search status",
        "acct.paused_word": "Paused",
        "acct.paused_rest": ("you marked that you found a job, so we're not searching "
                             "for you."),
        "acct.active_word": "Active",
        "acct.active_rest": ("we search daily and email you new matches (if you're active "
                             "in the last 5 days)."),
        "acct.resume": "Resume my searches",
        "acct.pause": "🎉 I found a job — pause searches",
        "acct.llm_ok": "Connection test passed — your key is saved (encrypted).",
        "acct.llm_removed": "Key removed.",
        "acct.delete_head": "Delete account",
        "acct.delete_note": ("Permanently deletes your account, profiles, matches and "
                             "applications. This cannot be undone. Type your email address "
                             "to confirm."),
        "acct.delete_confirm": "Permanently delete your account and all your data?",
        "acct.delete_btn": "Delete my account",
        "acct.email_mismatch": "The email you typed does not match.",
        "acct.not_deleted": "Your account was not deleted.",
        "acct.back": "Back to account",
        "llm.head": "AI generation (bring your own key)",
        "llm.note": ("CV and cover-letter generation runs on your LLM account. Recommended "
                     "free options: Google Gemini (aistudio.google.com) or Groq "
                     "(console.groq.com). Your key is stored encrypted, never shown back, "
                     "and you can remove it any time."),
        "llm.configured": "Configured:", "llm.default_model": "default model",
        "llm.remove": "Remove key", "llm.provider": "Provider",
        "llm.model": "Model (optional)", "llm.key": "API key",
        "llm.key_ph": "paste your API key (not needed for Ollama)",
        "llm.no_key": " — no key needed", "llm.test_save": "Test &amp; save",
        "llm.err_unknown": "Unknown provider.",
        "llm.err_key_required": "This provider requires an API key.",
        "llm.free_note": ("Free generation: up to {n} documents/day without a key. "
                          "Add your own key below for unlimited generation."),
        "acct.llm_needed": ("To generate a CV or cover letter we need an AI provider — "
                            "add a free key below (Google AI Studio or Groq, ~2 minutes)."),
        # ---- onboarding ----
        "ob.head": "Quick start — build your profile",
        "ob.sub": "Pick your profession and we'll suggest the typical skills.",
        "ob.step1": "Tell us your skills", "ob.step2": "We find matching jobs",
        "ob.step3": "You apply with one click", "ob.how": "How it works",
        "ob.profession": "Profession", "ob.choose": "Choose…",
        "ob.skills": "Skills", "ob.tap": "(tap to toggle)",
        "ob.select_first": "Select a profession to see suggested skills.",
        "ob.more": "Add more skills (comma-separated)",
        "ob.create": "Create profile",
        "ob.full_form": "Use the full form instead",
        "ob.change_later": "you can change everything later.",
        "ob.welcome": "Welcome 👋",
        "ob.welcome_sub": ("No profiles yet — create your first search profile in about "
                           "30 seconds."),
        "ob.title": "Quick start — Job Agent",
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
        "form.country": "Държава, в която живееш",
        "form.relocate": "Склонен съм да се преместя в чужбина",
        "form.relocate_hint": ("Когато е изключено, позиции, вързани с друга държава "
                               "(включително „remote“, изискващи да живееш там), се скриват."),
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
        "gaps.verified": "AI проверено",
        "gaps.honest": ("Бъди честен за тези при кандидатстване — или ги добави в профила си, "
                        "ако ги имаш."),
        "app.matches_ge": "Съвпадения ≥", "app.min": "мин.", "app.apply_thresh": "Приложи",
        "app.edit": "Редакция", "app.edit_title": "Редактирай този профил",
        "app.search_now": "Търси сега", "app.new_tab": "+ Нов",
        "app.searching": "⏳ Търсене…", "app.generating": "⏳ Генериране…",
        "app.gen_failed": "Генерирането се провали:",
        "app.search_done": ("Търсенето приключи — претърсени {pool} следени обяви, "
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
        # ---- documents ----
        "docs.kind_cv": "CV", "docs.kind_letter": "Мотивационно писмо",
        "docs.my": "Моите документи", "docs.document": "Документ", "docs.job": "Обява",
        "docs.created": "Създаден", "docs.removed": "(обявата е премахната)",
        "docs.none": "Все още няма документи — генерирай от някое съвпадение.",
        "docs.for": "За:",
        "docs.review_word": "Прегледай и редактирай преди употреба",
        "docs.review_rest": ("AI резултатът е чернова — финалният текст е твой. Редактирай "
                             "долу и запази; PDF-ът винаги използва последния ти текст."),
        "docs.saved_word": "Запазено.", "docs.saved_rest": "PDF-ът използва редактирания ти текст.",
        "docs.save": "Запази промените", "docs.download": "⬇ Свали PDF",
        "docs.regen_in": "Генерирай отново на {lang}", "docs.other_for": "{kind} за тази обява",
        # ---- account / settings ----
        "acct.heading": "Акаунт", "acct.joined": "регистриран на",
        "acct.profiles": "{n} профил(а) за търсене.",
        "acct.export": "Изтегли данните ми (JSON)",
        "acct.status_head": "Статус на търсенето",
        "acct.paused_word": "Пауза",
        "acct.paused_rest": "отбеляза, че си намерил работа, затова не търсим за теб.",
        "acct.active_word": "Активно",
        "acct.active_rest": ("търсим ежедневно и ти пращаме нови съвпадения по имейл "
                             "(ако си бил активен през последните 5 дни)."),
        "acct.resume": "Продължи търсенето",
        "acct.pause": "🎉 Намерих работа — спри търсенето",
        "acct.llm_ok": "Тестът мина успешно — ключът е запазен (криптиран).",
        "acct.llm_removed": "Ключът е премахнат.",
        "acct.delete_head": "Изтриване на акаунта",
        "acct.delete_note": ("Изтрива завинаги акаунта, профилите, съвпаденията и "
                             "кандидатурите ти. Действието е необратимо. Въведи имейл "
                             "адреса си за потвърждение."),
        "acct.delete_confirm": "Да изтрия ли завинаги акаунта и всичките ти данни?",
        "acct.delete_btn": "Изтрий акаунта ми",
        "acct.email_mismatch": "Въведеният имейл не съвпада.",
        "acct.not_deleted": "Акаунтът ти не е изтрит.",
        "acct.back": "Обратно към акаунта",
        "llm.head": "AI генериране (със собствен ключ)",
        "llm.note": ("Генерирането на CV и мотивационни писма върви през твоя LLM акаунт. "
                     "Препоръчани безплатни опции: Google Gemini (aistudio.google.com) или "
                     "Groq (console.groq.com). Ключът ти се съхранява криптиран, никога не "
                     "се показва обратно и можеш да го премахнеш по всяко време."),
        "llm.configured": "Настроен:", "llm.default_model": "модел по подразбиране",
        "llm.remove": "Премахни ключа", "llm.provider": "Доставчик",
        "llm.model": "Модел (по избор)", "llm.key": "API ключ",
        "llm.key_ph": "постави API ключа си (не е нужен за Ollama)",
        "llm.no_key": " — не изисква ключ", "llm.test_save": "Тествай и запази",
        "llm.err_unknown": "Непознат доставчик.",
        "llm.err_key_required": "Този доставчик изисква API ключ.",
        "llm.free_note": ("Безплатно генериране: до {n} документа на ден без ключ. "
                          "Добави свой ключ по-долу за генериране без лимит."),
        "acct.llm_needed": ("За да генерираме CV или мотивационно писмо, ни трябва AI — "
                            "добави безплатен ключ по-долу (Google AI Studio или Groq, "
                            "~2 минути)."),
        # ---- onboarding ----
        "ob.head": "Бърз старт — създай профила си",
        "ob.sub": "Избери професията си и ще ти предложим типичните умения.",
        "ob.step1": "Опиши уменията си", "ob.step2": "Ние намираме подходящи обяви",
        "ob.step3": "Кандидатстваш с един клик", "ob.how": "Как работи",
        "ob.profession": "Професия", "ob.choose": "Избери…",
        "ob.skills": "Умения", "ob.tap": "(докосни за избор)",
        "ob.select_first": "Избери професия, за да видиш предложени умения.",
        "ob.more": "Добави още умения (разделени със запетая)",
        "ob.create": "Създай профил",
        "ob.full_form": "Използвай пълната форма",
        "ob.change_later": "можеш да промениш всичко по-късно.",
        "ob.welcome": "Добре дошъл 👋",
        "ob.welcome_sub": ("Все още нямаш профили — създай първия си профил за търсене "
                           "за около 30 секунди."),
        "ob.title": "Бърз старт — Job Agent",
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
