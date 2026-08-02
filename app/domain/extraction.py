"""Requirement extraction from a pasted job description.

Rules-based and deterministic — no LLM call, so it costs nothing to run over many postings
(see LLM_COST_STRATEGY.md). It turns raw JD text into a list of ``{"text", "kind"}`` where
``kind`` is one of ``must`` / ``nice`` / ``resp`` / ``soft``. This is deliberately a cheap first pass;
a BYOK LLM refinement can slot in later behind the exact same return shape without touching
callers. Works for any profession — it keys off the JD's own section structure, not a fixed
technology list.

Heuristics, in order of importance:
- A bulleted line is always a list item, never a section header.
- A short, unbulleted, label-like line that names a known section switches the "current"
  bucket (must / nice / resp). Whole "drop" sections (benefits, about, perks…) are skipped.
- Boilerplate lines are dropped wherever they appear.
"""
import re

# Section headers steer classification (lowercased substring match). Bilingual BG/EN because
# the target market is BG + remote EU. Kept intentionally section-like, not generic phrases
# (a phrase like "experience with X" is a requirement, not a header) — and header detection
# only runs on non-bulleted lines anyway.
_NICE_HEADERS = ("nice to have", "nice-to-have", "bonus", "would be a plus", "a plus",
                 "preferred", "desirable", "advantage",
                 "helpful", "good to have", "предимство", "ще бъде предимство", "бонус")
_RESP_HEADERS = ("responsibilit", "what you'll do", "what you will do", "the role",
                 "role description", "duties", "day to day", "day-to-day",
                 "the impact you", "your impact", "you'll be", "you will be",
                 "daily routine", "what to expect", "your day", "a typical day",
                 "what awaits you", "your tasks", "your mission",
                 "отговорности", "какво ще правиш", "задължения", "какво те очаква",
                 "описание на дейността", "описание на длъжността", "основни задължения")
_MUST_HEADERS = ("requirement", "qualification", "must have", "must-have", "what you'll need",
                 "what you need", "what you'll bring", "what you bring", "your background",
                 "who you are", "we're looking for", "we are looking for",
                 "looking for", "you'll need", "you will need", "to thrive",
                 "the ideal candidate", "the perfect candidate", "if you have",
                 "love to hear from you", "you should apply", "great fit", "about you",
                 "skills", "изисквания", "необходими", "какво очакваме",
                 "търсим", "умения",
                 # sub-headers INSIDE a requirements block: unrecognised, they became gap items
                 # themselves ("Required Experience", "Tools & Systems" showed as missing skills)
                 "required experience", "required qualification", "your experience",
                 "tools & systems", "tools and systems", "tech stack", "technical stack",
                 "experience required", "qualifications required")
# Whole sections that never contain a requirement — switch into "drop" and skip until the
# next recognised header.
_DROP_HEADERS = ("about us", "about the", "about our", "who we are", "benefits", "perks",
                 "what we offer", "we offer", "our offer", "offer you", "the company offers",
                 # agencies write the offer in the third person: "In Return, They Offer:"
                 "in return", "they offer", "on offer", "we can offer", "you will receive",
                 "why join",
                 "why work", "our mission", "diversity", "compensation", "salary", "join us",
                 "our team", "interview process", "hiring process", "application process",
                 "what's in it for you", "why you'll love", "what you get", "you will get",
                 "tip from us", "goodies", "wellbeing", "health &", "growth &",
                 "purpose & culture", "our culture", "time-off perks",
                 "за нас", "за компанията", "ползи", "защо да", "предлагаме", "нашата мисия",
                 "ние предлагаме", "ще получиш", "придобивки",
                 "процес на интервю", "процес на подбор",
                 # "Компанията предлага:" / "Фирмата предлага:" — the -ме forms above only cover
                 # "предлагаМЕ", so the 3rd-person offer header slipped and leaked the benefits.
                 "предлага", "какво получаваш", "условия на труд", "социален пакет",
                 "нашето предложение", "бонуси",
                 # Multilingual drop-headers — the highest-leverage cross-language fix: an
                 # unrecognised header leaves benefits/privacy content in the "must" bucket, so
                 # recognising the OFFER / ABOUT / DATA-PROTECTION / HIRING-PROCESS section header
                 # in the posting's own language skips the whole block whatever its lines say.
                 "wir bieten", "das bieten wir", "unser angebot", "unsere benefits",
                 "deine vorteile", "über uns", "unser unternehmen", "datenschutz",
                 "bewerbungsprozess",                                             # de
                 "nous offrons", "ce que nous offrons", "t'offrir", "vous offrir",
                 "avantages", "à propos", "qui sommes-nous", "protection des données",
                 "confidentialité", "process de recrutement", "processus de recrutement",
                 "notre entreprise", "ce que nous proposons", "pourquoi nous rejoindre",
                 "rejoindre l'aventure", "pourquoi nous",                          # fr
                 "ofrecemos", "te ofrecemos", "beneficios", "protección de datos",
                 "sobre nosotros", "quiénes somos", "nuestra oferta",
                 "proceso de selección",                                          # es
                 "offriamo", "ti offriamo", "cosa offriamo", "protezione dei dati",
                 "chi siamo", "su di noi", "processo di selezione",               # it
                 "wij bieden", "wat wij bieden", "arbeidsvoorwaarden", "ons aanbod",
                 "gegevensbescherming", "over ons", "sollicitatieprocedure",      # nl
                 "oferujemy", "co oferujemy", "benefity", "ochrona danych",
                 "o nas", "o firmie", "proces rekrutacji",                        # pl
                 "προσφέρουμε", "παροχές", "προστασία δεδομένων", "σχετικά με",    # el
                 "nudimo", "što nudimo", "pogodnosti", "zaštita podataka",
                 "o nama", "o tvrtki",                                            # hr
                 "oferim", "ce oferim", "beneficii", "protecția datelor",
                 "despre noi", "procesul de recrutare",                           # ro
                 "мы предлагаем", "что мы предлагаем", "льготы", "защита данных",
                 "о компании", "о нас",                                           # ru
                 "ми пропонуємо", "що ми пропонуємо", "переваги", "захист даних",
                 "про компанію", "про нас")                                       # uk

# Stray boilerplate dropped even inside a kept section (real-world lines: trademark footers,
# marketing stats, EEO statements).
_NOISE = ("equal opportunity", "eeo", "we are an equal", "apply now", "how to apply",
          "registered trademark", "under license", "claim based on", "registered users",
          "fortune 100", "fortune 500", "кандидатствай",
          # closing / culture / employment-detail lines that are not skill requirements
          "if this feels like", "love to connect", "we'd love to hear", "we would love to hear",
          "full-time role", "full time role", "flexible hours", "no engagement tests",
          "time tracking", "official employment", "startup vibe", "no time tracking",
          # application-instruction closers (observed footers on dev.bg/zaplata postings)
          "send us your cv", "send your cv", "interested in the opportunity", "изпрати ни",
          "изпратете ни", "изпрати своето cv")

_BULLET = re.compile(r"^\s*(?:[-*•·▪●○◦→–—]|\d+[.)])\s+")
# A header line is short-ish and label-like: no sentence punctuation, optional trailing colon
# or question mark ("What are we looking for?" is a header too). 60 chars fits real headers
# like "As a Kotlin Multiplatform Developer, you'll be:" (observed on dev.bg).
_HEADERISH = re.compile(r"^[^.!?]{1,60}[:?]?\s*$")

# Salary / location-pipe lines ("📍 London / UK Remote | £85,000-£110,000 + Benefits").
_MONEY_RE = re.compile(r"[£$€]\s*\d|\d\s*(?:лв|BGN|EUR|USD|GBP)\b", re.I)
# Perk/benefit lines — they routinely appear WITHOUT a recognizable section header (observed
# live on dev.bg postings: bulleted straight after the requirements) and are never candidate
# requirements, whatever bucket they land in.
_BENEFIT_RE = re.compile(
    r"\b(annual leave|paid leave|days off|bonus days|health insurance|dental|sports? card|"
    r"multisport|coolfit|transportation card|travel allowance|company shuttle|snacks|"
    r"soft drinks|team buildings?|office parties|free parking|parking spot|chill-?out|foosball|referral program|"
    r"salary review|performance evaluation|vouchers|corporate discounts|discounts on|"
    r"newborn|birthday|first-grader|modern office|working environment|sabbatical|"
    r"unlimited mobile|goodies|psychologist|learning platform|supportive team|"
    r"tick every box|sending us your|up-to-date cv|annual bonus|"
    r"only shortlisted|approved candidates|treated (?:strictly |with strict )?confidential|"
    r"data protection legislation|"
    # perks that routinely slip a section header (a SumUp 'What we offer' block):
    r"pension (?:scheme|plan|contribution)|stock options|share options|equity|vsop|esop|"
    r"own a stake|referral bonus|sign-?on bonus|relocation (?:assistance|package|support)|"
    r"sports club|gym membership|fitness|wellbeing|hack days?|hack week|kita|childcare|"
    r"office lunch|free lunch|subsidi[sz]ed|meal (?:allowance|voucher)|flexible working hours|"
    r"remote (?:work )?budget|home[- ]office (?:budget|setup)|equipment budget|"
    r"opportunity to work (?:with|at|on)|healthy and safe workplace|prohibits harassment|"
    r"work[- ]life balance|paid (?:sick|parental|maternity|paternity)|"
    # perk lines that routinely land in the must-bucket with no section header (a Dreamix
    # 'What we offer' block bulleted straight after the requirements):
    r"massages?|warm and supportive|supportive work environment|unlimited home[- ]office|"
    r"summer office|winter office|company[- ]wide events?|knowledge[- ]sharing sessions?|"
    r"academic teaching|speaking engagements?|professional development|relax and unwind|"
    r"reach your full potential|certifications? and training|"
    r"days? (?:of )?(?:paid )?(?:annual )?(?:vacation|leave)|paid vacation|vacation days?|annual salary review|share incentivi[sz]ation|"
    r"equipment reimbursement|career enhancement|workshops?, conferences|hackat|"
    r"remote[- ]first policy|global mission|confidentiality of all applications|"
    r"flexible work hours|tech deep dive|"
    r"отпуск|здравна осигуровка|спортна карта|мултиспорт|ваучери|тиймбилдинг\w*|"
    r"карта за транспорт|бонус за|пенси\w*|релокац\w*|обяд\w*|"
    # BG perk lines from live cards, stale short postings ("Коректно и навременно заплащане",
    # "Обособена релакс зона (кино кът, тенис маса)", "Млад, мотивиран и сплотен екип").
    # NB: Cyrillic cues need \w* before the closing \b — "тиймбилдингИ" was slipping it.
    r"заплащане|релакс зона|кино кът|тенис маса|сплотен екип|работна среда|"
    r"фирмени събития|мотивиран и\w* екип|безплатн\w*|намаления|отстъпки)\b", re.I)

# Application / data-privacy footer boilerplate — a consent-and-processing block that closes most
# EU/BG postings (dev.bg, zaplata). It is keyed to the CONSENT/PROCESSING phrasing, NOT the bare
# words "gdpr"/"privacy" — those are legitimate REQUIREMENTS on some roles ("Familiarity with the
# EU AI Act, GDPR and responsible-AI practices" must survive). Dropped wherever it appears.
_LEGAL_RE = re.compile(
    r"by applying (?:for|to) this\b|you voluntarily (?:agree|submit)|voluntarily agree and submit|"
    r"(?:personal data|personal information) (?:that )?you provide|"
    r"process(?:es|ing)? (?:your |of your )?personal (?:data|information)|"
    r"your personal (?:data|information) (?:will|shall|may) be|"
    r"for the purpose[s]? of (?:the )?(?:selection|recruitment|hiring)|"
    r"in accordance with (?:the )?(?:gdpr|applicable data)|applicable data[- ]protection|"
    r"data protection (?:law|legislation|regulation)|(?:a )?european job applicant|"
    r"see the privacy (?:notice|policy)|collects and processes personal|"
    r"transferred to (?:other )?data controllers|"
    r"recruitment licen[cs]e|licen[cs]e (?:no\.?|number|№|issued)|"
    r"^[\w .,&'-]{2,42}\b(?:ltd|gmbh|ood|eood|inc|llc|ад|еоод|оод)\.?$|"
    # Bulgarian application/consent footer — every zaplata.bg / recruitment-agency posting ends
    # with it (ЗЗЛД = the BG data-protection act, НАЗ licence, "only approved candidates").
    r"ззлд|защитени по смисъла|лиценз (?:от|№|no)|национална агенция по заетостта|"
    r"за целите на (?:подбор|настоящия подбор|селекция)|"
    r"(?:само )?(?:предварително )?одобрени(?:те)? кандидати|"
    r"ще се свърже[мн]? (?:само )?с|благодарим (?:ви|на всички)|"
    r"изпратете (?:ни )?(?:вашата |своята )?(?:автобиограф|cv|молба)|"
    r"кандидатствай(?:те)? (?:чрез|през|на)|предоставените от вас данни|"
    r"личните ви данни|обработване на лични данни|защита на личните данни|"
    r"(?:пълна|строга) (?:конфиденциалност|поверителност)|разглеждан\w* при конфиденциалност|"
    r"представлява интерес за вас|изпратете[^.]{0,40}автобиограф|ще се радваме да работим|"
    r"protected by the law|protected within the meaning|consult our privacy notice|"
    r"privacy notice \(http|data of applicants is protected|data provided by you is|"
    # Same consent/selection footer across the source languages. Formulaic and unambiguous —
    # unlike marketing prose, these phrases are never a skill requirement, so enumerating them
    # is safe (the multilingual DROP headers only help when the section IS headed).
    r"mit ihrer bewerbung|personenbezogene[nr]? daten|verarbeitung ihrer|datenschutzerkl|"
    r"dsgvo|nur ausgew(?:ä|ae)hlte|ausgew(?:ä|ae)hlte (?:kandidaten|bewerber)|"       # de
    r"en postulant|donn(?:é|e)es personnelles|traitement de vos donn|rgpd|"
    r"seuls les candidats|politique de confidentialit|"                               # fr
    r"al (?:inscribirte|aplicar|postular)|datos personales|tratamiento de (?:tus|sus) datos|"
    r"candidatos (?:seleccionados|preseleccionados)|protecci(?:ó|o)n de datos|"       # es
    r"candidandoti|dati personali|trattamento dei dati|candidati selezionati|"
    r"informativa (?:sulla )?privacy|"                                                # it
    r"door te solliciteren|persoonsgegevens|verwerking van je|geselecteerde kandidaten|"  # nl
    r"aplikuj(?:ąc|ac)|dane osobowe|przetwarzanie danych|rodo|wybrani kandydaci|"     # pl
    r"prelucrarea datelor|datele (?:dvs\.? )?personale|candida(?:ț|t)ii selecta(?:ț|t)i|"  # ro
    r"osobnih podataka|obradu podataka|odabrani kandidati|"                           # hr
    r"προσωπικ(?:ώ|ω)ν δεδομ(?:έ|ε)νων|επεξεργασ(?:ί|ι)α δεδομ(?:έ|ε)νων|"            # el
    r"персональных данных|обработку данных|отобранные кандидаты|"                     # ru
    r"персональних даних|обробку даних|в(?:і|i)д(?:і|i)бран(?:і|i) кандидати", re.I)  # uk

# Terms of EMPLOYMENT (hours, contract type, start date, shift pattern) — they answer "what is the
# job", not "what must the candidate have", so they are never gaps. Observed leaking from EURES
# (Finnish/Irish postings list them as plain bullets with no section header) and BG agency ads.
_TERMS_RE = re.compile(
    r"\b\d{1,2}\s*(?:hours?|hrs?)\s*(?:per|a|/)\s*week|\bworking hours?\b|\bwork(?:ing)? time\b|"
    r"\bovertime\b|\bshift work\b|\bfull[- ]time\b|\bpart[- ]time\b|"
    r"permanent (?:employment )?contract|fixed[- ]term contract|employment (?:begins|starts)|"
    r"start date|starting date|immediate start|\basap\b|"
    r"schedule (?:&|and) location|\bmonday to friday\b|"
    r"работно време|работни часа|на смени|извънреден труд|"
    r"(?:постоянна|целогодишна|дългосрочна) заетост|трудов договор|срочен договор|"
    r"начало на работа|от понеделник до петък|командировк\w*|условия на труд|"
    # Employment terms in the source languages (hours / contract type / start date).
    r"wochenstunden|stunden pro woche|arbeitsvertrag|unbefristet|befristet|arbeitsbeginn|"
    r"vollzeit|teilzeit|schichtarbeit|"                                               # de
    r"heures par semaine|contrat (?:à|a) dur(?:é|e)e|\bcdi\b|\bcdd\b|temps (?:plein|partiel)|"
    r"prise de poste|"                                                                # fr
    r"horas (?:semanales|a la semana)|contrato (?:indefinido|temporal|de trabajo)|"
    r"jornada (?:completa|parcial)|media jornada|incorporaci(?:ó|o)n inmediata|"      # es
    r"ore settimanali|contratto a tempo (?:indeterminato|determinato)|tempo pieno|"   # it
    r"uur per week|arbeidsovereenkomst|vast contract|fulltime|parttime|startdatum|"   # nl
    r"godzin tygodniowo|umowa (?:o prac|zlecenie)|pe(?:ł|l)ny etat|rozpocz(?:ę|e)cie pracy|"  # pl
    r"ore pe s(?:ă|a)pt(?:ă|a)m(?:â|a)n(?:ă|a)|contract pe perioad|norm(?:ă|a) (?:î|i)ntreag",  # ro
    re.I)
# Company self-narrative ("We're on a mission...", "Our customers...", "GitLab is the/a/where...")
# plus what-the-company-gives-you sentences ("You will have the opportunity for fully remote...").
_MARKETING_RE = re.compile(
    r"^(?:we['’]?re\b|we\s+are\b|we['’]?ve\b|we\s+want\b|we\s+build\b|our\s|join\s+us\b"
    r"|you(?:['’]ll|\s+will)?\s+(?:have|get|enjoy)\b)"
    r"|^as the (?:team|company|people) behind\b"
    r"|^[A-Z][\w.&-]*\s+is\s+(?:the|a|an|where)\b", re.I)
# Signals that a sentence is genuinely about the candidate's qualifications — overrides the
# marketing filter ("We are looking for someone with 5+ years..." must survive). Bare "years"
# is deliberately NOT a signal ("grown a lot in the last 10 years in the UK" is narrative);
# only the "N+ years of ..." qualification shape counts.
_REQ_SIGNAL_RE = re.compile(
    r"\b(experience|proficien\w*|knowledge|familiar\w*|degree|fluen\w*|skills?|"
    r"ability|expertise|hands-on|track record|understanding|качеств|опит|познания|"
    r"умения|владеене|образование)\b|\d+\s*\+?\s*(?:years?|години)\s+(?:of|опит|в)\b", re.I)
# Overriding the marketing filter takes a STRONG qualification signal — bare "skills"/"ability"
# is not enough ("...bright people eager to develop their professional skills" is narrative,
# "We are looking for someone with 5+ years of Kotlin experience" is a requirement).
_STRONG_SIGNAL_RE = re.compile(
    r"\b(experience|proficien\w*|knowledge|degree|fluen\w*|expertise|track record|"
    r"опит|познания|владеене|образование)\b"
    r"|\d+\s*\+?\s*(?:years?|години)\s+(?:of|опит|в)\b", re.I)
# Company self-praise that a strong-signal word ('25 years of experience' — of the COMPANY, not
# the candidate) would otherwise sneak past the marketing filter. These describe the employer's
# scale/history, never a requirement, so they're dropped outright ("2,700+ professional experts,
# half a billion people worldwide impacted by our work, we believe we've got the numbers…").
_COMPANY_BOAST_RE = re.compile(
    r"professional experts|people worldwide|worldwide impacted|impacted by our|"
    r"we believe we|we['’]?ve got the numbers|billion (?:people|users|customers)|"
    r"millions? of (?:people|users|customers)|trusted by|founded in \d{4}|our mission is|"
    r"years? in business|we serve|we['’]?ve grown|our clients|proud to|"
    r"culture is what|what makes us (?:different|special)|we (?:strongly )?believe in", re.I)

# DEI / "apply anyway" encouragement closers. They contain qualification words ("skills",
# "requirements") so the marketing filter and the req-signal override let them through as musts —
# but they're never a requirement (an accountant JD's "we recognize everyone carries a unique set
# of valuable skills" / "if you think you could have an impact even though you don't meet 100% of
# the requirements"). Dropped outright so they don't sit in the gaps panel as uncoverable musts.
_ENCOURAGEMENT_RE = re.compile(
    r"we recognize that everyone|unique set of (?:valuable )?(?:skills|experience)|"
    r"if you think you (?:could|can|might)|even (?:though|if) you (?:do\s*n['’]?t|don['’]?t) "
    r"(?:meet|have|tick|check)|do\s*n['’]?t meet (?:100%|all|every|the)|"
    r"we (?:strongly )?encourage(?:d)? (?:you|everyone|all|applicants)|encouraged to apply|"
    r"equal[- ]opportunit|we (?:value|celebrate|embrace) diversity|diverse and inclusive|"
    r"regardless of (?:race|gender|age|religion|sexual|disability|background)|"
    r"an inclusive (?:workplace|environment)|committed to (?:diversity|inclusion|equal)", re.I)

# Personality / soft-skill lines ("Team player with strong communication skills...",
# "Performance-oriented mindset—you care about..."). Nobody lists these in a skills profile,
# so scoring them as gaps is noise — they become kind="soft": extracted for transparency,
# zero weight, hidden from the gaps panel (owner feedback on the A1 card).
_SOFT_RE = re.compile(
    r"\b(team player|communication skills|interpersonal|mindset|attention to detail|"
    r"self-motivat\w*|proactive|positive attitude|can-do|work ethic|fast learner|"
    r"eager to learn|passion\w*|curiosity|curious|adaptab\w*|problem[- ]solv\w*|"
    r"ability to (?:independently\s+)?(?:learn|integrate|adapt|collaborate|work|write clean)|"
    r"focus on results|clean code|build(?:ing)? a team|emotionally balanced|"
    r"supportive(?:,| team)|strong analytical thinking|"
    r"responsibilit\w* and reliabilit\w*|organi[sz]ational skills|"
    # ATTITUDE FRAMES: "you care deeply about reliability", "you take pride in clean code" —
    # what makes these unscoreable is the frame, not the noun inside it. There is nothing in a
    # profile to weigh "cares about X" against, so they're soft whatever X is. (A checkable
    # phrasing of the same noun — "experience building reliable systems" — stays a requirement.)
    r"(?:you )?care[sd]? (?:deeply )?about|take[s]? pride in|you enjoy|you thrive|"
    r"comfortable (?:with|working)|excited (?:by|about)|motivated by|"
    r"analytical (?:thinking|mind)|detail[- ]oriented|willingness to (?:learn|travel|work)|"
    # Bulgarian personal-quality lines ("Персонални качества:" blocks on zaplata.bg) — they are
    # character traits, never a skill anyone lists in a profile, so scoring them as gaps is noise.
    r"комуникативн\w*|екипен играч|работа в екип|лична мотивация|адаптивн\w*|"
    r"отговорност|прецизност|решителност|организираност|аналитично мислене|"
    r"внимание към детайл\w*|инициативност|лоялност|дискретност|"
    r"желание за (?:работа|учене|развитие)|позитивн\w*|усмихнат\w*|"
    # Personal qualities in the source languages. These only RECLASSIFY must/nice -> soft
    # (kept for context, zero weight, hidden from the gaps panel) — never dropped.
    r"teamf(?:ä|ae)higkeit|zuverl(?:ä|ae)ssigkeit|verantwortungsbewusstsein|"
    r"kommunikationsst(?:ä|ae)rke|eigeninitiative|belastbarkeit|lernbereitschaft|"
    r"sorgfalt|flexibilit(?:ä|ae)t|"                                                  # de
    r"esprit d['’]?(?:é|e)quipe|rigueur|sens des responsabilit\w*|autonomie|"
    r"bon relationnel|capacit(?:é|e) d['’]?adaptation|dynamisme|"                     # fr
    r"trabajo en equipo|proactividad|capacidad de adaptaci\w*|orientaci(?:ó|o)n al detalle|"  # es
    r"lavor(?:o|are) in team|affidabilit\w*|senso di responsabilit\w*|"
    r"capacit(?:à|a) di lavorare|precisione|flessibilit\w*|"                             # it
    r"teamplayer|communicatieve vaardigheden|zelfstandig|nauwkeurig|"
    r"verantwoordelijkheidsgevoel|"                                                   # nl
    r"praca w zespole|odpowiedzialno(?:ś|s)(?:ć|c)|komunikatywno\w*|samodzielno\w*|"
    r"dok(?:ł|l)adno(?:ś|s)(?:ć|c)|zaanga(?:ż|z)owanie|"                              # pl
    r"lucru (?:î|i)n echip\w*|responsabilitate|aten(?:ț|t)ie la detalii)\b", re.I)       # ro

# Typographic quotes/dashes -> ASCII before ANY matching. Real postings (Yettel via dev.bg)
# use U+2019 in "What's in It for you:" / "What you'll do:", which silently missed every
# apostrophe-bearing header above and dumped the whole benefits section into the must bucket.
_TYPOGRAPHY = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})

# Sentence split for over-long prose. NOT after a common abbreviation: splitting on every
# "." turned "tools (e.g. Claude Code, Codex) across CI" into the fragments "…tools (e.g." and
# "Claude Code, Codex) across CI" in the gaps panel. Semicolons only break a part that is STILL
# too long afterwards (they separate list items, not sentences).
_SENT_SPLIT = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)(?<!\bInc)(?<!\bLtd)\.\s+")
_SEMI_SPLIT = re.compile(r";\s+")

_MIN_LEN = 8      # shorter than this is a fragment, not a requirement
_MAX_LEN = 180    # longer than this is prose; we try to split it into sentences
_DROP = "drop"


def _match_header(line: str) -> str | None:
    """Return the bucket a header line names, or None if it isn't a recognised header."""
    low = line.lower()
    # nice/resp take priority over must ("nice to have skills" contains "skills").
    if any(h in low for h in _NICE_HEADERS):
        return "nice"
    if any(h in low for h in _RESP_HEADERS):
        return "resp"
    if any(h in low for h in _DROP_HEADERS):
        return _DROP
    if any(h in low for h in _MUST_HEADERS):
        return "must"
    return None


_INLINE_LABEL = re.compile(r"^([^:]{3,22}):\s+(?=\S)")


def _inline_label(cleaned: str, current: str) -> tuple[str, str]:
    """A section label can arrive INLINE rather than on its own line — "Nice to have: our cloud
    platform; data versioning…". Without this the whole line scores as a must and inflates the
    gaps panel. Only NICE is honoured: promoting a line to must/resp from a prefix is riskier
    (a sentence can open with any word before a colon) and buys nothing."""
    m = _INLINE_LABEL.match(cleaned)
    if m and _match_header(m.group(1)) == "nice":
        return "nice", cleaned[m.end():]
    return current, cleaned


def _is_noise(line: str) -> bool:
    low = line.lower()
    return any(n in low for n in _NOISE)


def _clean(line: str) -> str:
    line = _BULLET.sub("", line)
    line = line.strip(" \t•·-*–—→●○◦▪")
    line = re.sub(r"^[\W_]+", "", line)   # leading emoji/symbols ("🚀 We're on a mission...")
    return re.sub(r"\s+", " ", line).strip()


def _keep(cleaned: str, *, seen_header: bool, is_bullet: bool, labelled: bool = False) -> bool:
    """Line-level boilerplate defence, tuned on real JDs (GitLab/Monzo/Stripe):
    - salary/currency lines are never requirements;
    - company self-narrative ("We're on a mission...", "X is the platform for...") is dropped
      unless the sentence carries a genuine qualification signal ("We are looking for someone
      with 5+ years..." survives);
    - before the first recognised section header (the marketing preamble), only bullets and
      signal-bearing lines are kept — bare pasted requirement lists still work, prose intros
      don't pollute the must-bucket."""
    if _MONEY_RE.search(cleaned):
        return False
    if _BENEFIT_RE.search(cleaned):
        return False
    if _LEGAL_RE.search(cleaned):           # application-consent / data-privacy footer boilerplate
        return False
    if _TERMS_RE.search(cleaned):           # terms of employment — describes the job, not the person
        return False
    if _COMPANY_BOAST_RE.search(cleaned):   # employer self-praise, even if it says "N years…"
        return False
    if _ENCOURAGEMENT_RE.search(cleaned):   # DEI / "apply even if you don't meet everything"
        return False
    # `labelled`: the line came in under an explicit requirement label ("Nice to have: Our cloud
    # platform…"), so the company-narrative filter must not eat it for opening with "Our".
    if not labelled and _MARKETING_RE.match(cleaned) and not _STRONG_SIGNAL_RE.search(cleaned):
        return False
    if not seen_header and not is_bullet and not _REQ_SIGNAL_RE.search(cleaned):
        return False
    return True


def extract_requirements(text: str, cap: int = 40) -> list[dict]:
    """Return a de-duplicated list of ``{"text", "kind"}`` requirement entries, capped."""
    if not text:
        return []
    text = text.translate(_TYPOGRAPHY)
    current = "must"  # bucket for content seen before any recognised header
    seen_header = False
    out: list[dict] = []
    seen: set[str] = set()

    def add(phrase: str, kind: str, is_bullet: bool, labelled: bool = False) -> None:
        phrase = phrase.strip()
        if not (_MIN_LEN <= len(phrase) <= _MAX_LEN):
            return
        if not _keep(phrase, seen_header=seen_header, is_bullet=is_bullet, labelled=labelled):
            return
        key = phrase.lower()
        if key in seen:
            return
        seen.add(key)
        if kind in ("must", "nice") and _SOFT_RE.search(phrase):
            kind = "soft"
        out.append({"text": phrase, "kind": kind})

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_bullet = bool(_BULLET.match(line))
        # Only unbulleted, label-like lines can be section headers. A colon-terminated line is
        # label-like at any reasonable length ("Our gratitude for the job done will be eternal,
        # but we'll also offer you:" is 74 chars and MUST hit the drop headers). A trailing
        # ellipsis is header punctuation too — "We'd love to hear from you if…" (Monzo) is
        # the must header that classified an entire JD as responsibilities when missed.
        # Only a true ELLIPSIS ('…'/'...') is header punctuation; a single trailing period
        # stays sentence punctuation ("Metodi is looking for..." must not become a header).
        hline = re.sub(r"(?:\.{3}|…)+\s*$", "", line).strip()
        if not is_bullet and hline and (_HEADERISH.match(hline)
                                        or (line.endswith(":") and len(line) <= 100)):
            hdr = _match_header(hline)
            if hdr:
                current = hdr
                seen_header = True
                continue
            # An UNRECOGNISED label line ending in ':' is still a label, never a requirement
            # ("The perfect candidate meets the following:") — skip it, keep the bucket.
            if line.endswith(":"):
                continue
        if current == _DROP or _is_noise(line):
            continue
        cleaned = _clean(line)
        current_line, cleaned = _inline_label(cleaned, current)
        if len(cleaned) > _MAX_LEN:
            # Prose paragraph: keep sentence-sized pieces rather than the whole block.
            for sentence in _SENT_SPLIT.split(cleaned):
                parts = ([sentence] if len(sentence) <= _MAX_LEN
                         else _SEMI_SPLIT.split(sentence))
                for part in parts:
                    add(part, current_line, is_bullet, labelled=current_line != current)
                if len(out) >= cap:
                    break
        else:
            add(cleaned, current_line, is_bullet, labelled=current_line != current)
        if len(out) >= cap:
            break
    return out[:cap]
