"""Tests for the rules-based requirement extractor."""
from app.domain.extraction import extract_requirements

JD = """
About the company
We are a fast-growing fintech. We are an equal opportunity employer.

Requirements:
- 5+ years of Android development with Kotlin
- Strong experience with Jetpack Compose and Coroutines
- Experience with CI/CD pipelines

Nice to have:
- Kotlin Multiplatform (KMP)
- Experience with fintech or payments

Responsibilities:
- Build and ship features for millions of users
- Mentor junior engineers

Benefits:
- Competitive salary and stock options
"""


def _texts(reqs, kind=None):
    return [r["text"].lower() for r in reqs if kind is None or r["kind"] == kind]


def test_returns_text_kind_dicts():
    reqs = extract_requirements(JD)
    assert reqs and all(set(r) == {"text", "kind"} for r in reqs)
    assert all(r["kind"] in {"must", "nice", "resp"} for r in reqs)


def test_must_have_section_captured():
    musts = _texts(extract_requirements(JD), "must")
    assert any("kotlin" in t for t in musts)
    assert any("compose" in t for t in musts)        # was mis-read as a header before the fix
    assert any("ci/cd" in t for t in musts)


def test_nice_to_have_classified():
    nices = _texts(extract_requirements(JD), "nice")
    assert any("kmp" in t or "multiplatform" in t for t in nices)
    assert any("fintech" in t for t in nices)


def test_responsibilities_classified():
    resp = _texts(extract_requirements(JD), "resp")
    assert any("mentor" in t for t in resp)


def test_boilerplate_and_benefits_dropped():
    all_text = " ".join(_texts(extract_requirements(JD)))
    assert "equal opportunity" not in all_text
    assert "competitive salary" not in all_text and "stock option" not in all_text
    assert "fast-growing" not in all_text  # the About intro


def test_dei_and_apply_anyway_closers_dropped():
    # non-tech JDs end with encouragement/DEI prose that carries "skills"/"requirements" and so
    # slipped past the marketing filter as uncoverable musts — must be dropped now.
    jd = ("Requirements:\n"
          "- Minimum 3 years of experience in accounting\n"
          "- Proficiency in Excel\n"
          "We recognize that everyone carries a unique set of valuable skills.\n"
          "If you think you could have an impact even though you don't meet 100% of the "
          "requirements, we encourage you to apply.\n"
          "We are committed to diversity and equal opportunity regardless of gender or background.")
    kept = " ".join(_texts(extract_requirements(jd))).lower()
    assert "3 years of experience" in kept and "excel" in kept   # real requirements survive
    assert "we recognize that everyone" not in kept
    assert "encourage you to apply" not in kept
    assert "unique set of valuable skills" not in kept
    assert "regardless of gender" not in kept


def test_bulleted_line_is_never_a_header():
    # "Strong experience with ..." contains a header keyword but is a bullet -> stays an item.
    reqs = extract_requirements("Requirements:\n- Strong experience with Kotlin skills")
    assert len(reqs) == 1 and reqs[0]["kind"] == "must"
    assert "kotlin" in reqs[0]["text"].lower()


def test_bulgarian_headers():
    jd = "Изисквания:\n- Опит с Kotlin\nПредимство:\n- Опит с KMP"
    reqs = extract_requirements(jd)
    assert any(r["kind"] == "must" for r in reqs)
    assert any(r["kind"] == "nice" for r in reqs)


def test_dedup_and_cap():
    jd = "Requirements:\n" + "\n".join(["- Kotlin expertise"] * 5)
    assert len(extract_requirements(jd)) == 1
    many = "Requirements:\n" + "\n".join(f"- Skill number {i}" for i in range(60))
    assert len(extract_requirements(many, cap=10)) == 10


def test_empty_input():
    assert extract_requirements("") == []
    assert extract_requirements(None) == []


def test_short_fragments_dropped():
    # "- Go" (2 chars) is below the min length and should be dropped.
    reqs = extract_requirements("Requirements:\n- Go\n- Kotlin and Compose experience")
    assert all(len(r["text"]) >= 8 for r in reqs)


# ---- real-world boilerplate (observed live from GitLab / Monzo postings) ----
GITLAB_PREAMBLE = """GitLab is the intelligent orchestration platform for DevSecOps.
More than 50 million registered users and more than 50% of the Fortune 100* trust GitLab to ship better, more secure software faster.
GitLab is where careers accelerate, innovation flourishes, and every voice is valued.
Co-create the future with us as we build technology that transforms how the world develops software.
What you'll bring:
- 5+ years of experience with Ruby on Rails
- Experience with PostgreSQL
Fortune 500® is a registered trademark of Fortune Media IP Limited, used under license.
Claim based on GitLab data."""

MONZO_PREAMBLE = """🚀 We're on a mission to make money work for everyone.
We're waving goodbye to the complicated and confusing ways of traditional banking.
After starting as a prepaid card, our product offering has grown a lot in the last 10 years in the UK.
Our UK customers can also save, invest and combine their pensions with us.
We're not about selling products - we want to solve problems and change lives through Monzo 💗
📍 London / UK Remote | £85,000-£110,000 + Incentive Awards tied to your performance + Benefits
What you'll need:
- Experience with Kubernetes and AWS
The interview process:
Our interview process involves 3 main stages. We promise not to ask you any brain teasers or trick questions!"""


def test_gitlab_marketing_preamble_dropped():
    texts = " ".join(r["text"].lower() for r in extract_requirements(GITLAB_PREAMBLE))
    assert "orchestration platform" not in texts        # company self-description
    assert "registered users" not in texts              # marketing stat
    assert "careers accelerate" not in texts
    assert "co-create" not in texts
    assert "registered trademark" not in texts and "claim based" not in texts
    # the real requirements survive, in the must bucket
    musts = [r["text"].lower() for r in extract_requirements(GITLAB_PREAMBLE)
             if r["kind"] == "must"]
    assert any("ruby on rails" in t for t in musts)
    assert any("postgresql" in t for t in musts)


def test_monzo_marketing_salary_and_interview_dropped():
    texts = " ".join(r["text"].lower() for r in extract_requirements(MONZO_PREAMBLE))
    assert "mission" not in texts                       # emoji-led marketing
    assert "traditional banking" not in texts
    assert "prepaid card" not in texts
    assert "pensions" not in texts
    assert "£" not in texts and "85,000" not in texts   # salary line
    assert "interview process" not in texts             # dropped section
    assert "brain teasers" not in texts
    musts = [r["text"].lower() for r in extract_requirements(MONZO_PREAMBLE)
             if r["kind"] == "must"]
    assert any("kubernetes" in t for t in musts)


# benefits observed live on a dev.bg posting — they arrived bulleted WITHOUT a recognizable
# section header and polluted the requirements ("45% with 1 of 26 covered" incident)
DEVBG_BENEFITS = """Requirements:
- Around 3–5 years of experience in software development with Java or .NET
- Good understanding of multi-threaded software applications
- Performance evaluation & salary review twice a year
- 25 days paid annual leave
- Work from home option -2 days weekly
- Additional health insurance – premium package
- Fully paid annual transportation card
- Fully paid Sports card
- Free company shuttle to the office
- Team building events and office parties
- Referral Program
- Free snacks, soft drinks, coffee, and fruit are always available
- Birthday, newborn baby, and first-grader bonuses
- Corporate discounts in various shops and restaurants
- State-of-the-art modern office
- Positive working environment and chill-out zone (PS4, foosball-table, and lazy chairs)
All applications will be treated strictly confidentially and only the approved candidates will be invited to an interview."""


def test_headerless_benefit_bullets_dropped():
    reqs = extract_requirements(DEVBG_BENEFITS)
    texts = " ".join(r["text"].lower() for r in reqs)
    for bad in ("annual leave", "sports card", "snacks", "shuttle", "referral",
                "team building", "salary review", "health insurance", "chill-out",
                "modern office", "confidential", "birthday"):
        assert bad not in texts, f"benefit leaked: {bad}"
    musts = [r["text"].lower() for r in reqs if r["kind"] == "must"]
    assert any("java or .net" in t for t in musts)          # real requirements survive
    assert any("multi-threaded" in t for t in musts)


# observed live: Yettel (via dev.bg) uses TYPOGRAPHIC apostrophes (U+2019) in its headers,
# which missed every "what you'll..." pattern and dumped the whole perks section into musts
YETTEL = """Whether you’re just starting out or bringing years of experience, at Yettel we believe the right role isn’t just about responsibilities — it’s about growth, impact, and being part of something meaningful.
The impact you’ll make:
The Android Software Developer will be responsible for designing, developing, and maintaining high-quality mobile applications for the Android platform.
What you’ll do:
Develop and maintain Android applications focused on quality and performance
Write tests to ensure app stability and quality
To thrive in this role, you’ll need:
Mobile Development Expertise: Proven experience designing and building high-quality Android apps with Kotlin and Java.
API Integration: Experience connecting mobile apps with backend services via RESTful APIs.
What’s in It for you:
Financial & Time-Off Perks
21 days of paid leave (birthday included!)
1-month sabbatical every 5 years
Food & gift vouchers every month
Mobile & Tech Goodies
Unlimited mobile & internet
Exclusive discounts on devices and accessories
Health & Wellbeing
Wellbeing support: in-house psychologist, sports at the office, expert talks
Growth & Learning
Top online learning platform access
Supportive team and manager
Purpose & Culture
Do work that matters — we create real impact
A Tip from Us:
AI is great, but this part is all you! We encourage AI at work, but for your application, we’d love to hear your own thoughts, experiences, and motivation.
You don’t need to tick every box! If this role excites you, go for it! We value potential over perfection.
Join Yettel now by sending us your up-to-date CV.
Only shortlisted applicants will be contacted with information about next steps of our selection process.
Applicants are treated with strict confidentiality following the applicable personal data protection legislation."""


def test_typographic_apostrophe_headers_recognised():
    reqs = extract_requirements(YETTEL)
    texts = " ".join(r["text"].lower() for r in reqs)
    # nothing from the benefits/outreach tail may leak
    for bad in ("goodies", "unlimited mobile", "discounts", "wellbeing", "psychologist",
                "learning platform", "supportive team", "tip from us", "tick every box",
                "sending us your", "shortlisted", "confidential", "vouchers", "sabbatical",
                "paid leave", "real impact"):
        assert bad not in texts, f"leaked: {bad}"
    # requirements land in must, duties in resp — the sections were actually recognised
    musts = [r["text"].lower() for r in reqs if r["kind"] == "must"]
    resp = [r["text"].lower() for r in reqs if r["kind"] == "resp"]
    assert any("kotlin and java" in t for t in musts)
    assert any("restful apis" in t for t in musts)
    assert any("develop and maintain android applications" in t for t in resp)
    assert not any("marketing" in r["kind"] for r in reqs)  # sanity on kinds
    # the opening marketing paragraph is gone too
    assert "something meaningful" not in texts


# observed live: Accedia (via dev.bg) — question-mark header, 46-char resp header, unrecognized
# label lines ("The perfect candidate meets the following:"), "advantage" nice-section, and a
# marketing opener whose only signal word is the weak "skills"
ACCEDIA = """What are we looking for?
We are expanding our team of Mobile software developers and we are looking for bright people who enjoy dynamics and are eager to learn and develop their professional skills. You will have the opportunity for fully remote or hybrid work (remote and in the office in Sofia)
As a Kotlin Multiplatform Developer, you’ll be:
Work in a supportive environment on projects for international clients.
Continuously learn new technologies, take part in knowledge-sharing initiatives (e.g. internal trainings), and pursue professional certifications.
Requirements
The perfect candidate meets the following:
Solid understanding of Swift or Kotlin.
Experience building native UI for iOS (SwiftUI, UIKit) or Android (Jetpack Compose, XML).
Fluency in English.
The following will be considered an advantage:
Experience with Kotlin Multiplatform (KMP).
Familiarity with Objective-C and/or Java.
What we offer:
Career growth – We do 4 performance and salary reviews a year for every team member.
About us
Accedia is a premier European IT services company, specializing in technology consulting."""


def test_accedia_sections_classified_correctly():
    reqs = extract_requirements(ACCEDIA)
    texts = " ".join(r["text"].lower() for r in reqs)
    # marketing / labels / offer / about never leak
    for bad in ("expanding our team", "bright people", "opportunity for fully remote",
                "meets the following", "considered an advantage", "career growth",
                "premier european", "salary review"):
        assert bad not in texts, f"leaked: {bad}"
    musts = [r["text"].lower() for r in reqs if r["kind"] == "must"]
    nices = [r["text"].lower() for r in reqs if r["kind"] == "nice"]
    resp = [r["text"].lower() for r in reqs if r["kind"] == "resp"]
    assert any("swift or kotlin" in t for t in musts)
    assert any("fluency in english" in t for t in musts)
    assert any("multiplatform" in t for t in nices)        # advantage section -> nice
    assert any("objective-c" in t for t in nices)
    assert any("supportive environment" in t for t in resp)  # "you'll be:" -> resp
    assert any("knowledge-sharing" in t for t in resp)


# observed live: A1 Bulgaria — "Would you like to join us?" hits the join-us drop header, so
# the FOLLOWING sections must be recognised or the whole JD is swallowed (0 requirements ->
# pure-semantic 86% ring). Long colon lines ("...we'll also offer you:") are drop headers too.
A1 = """Strength. Care. Growth
Our wide portfolio has long past the telecom services, and we are now offering digital solutions to millions of corporate, public, and private customers.
Would you like to join us?
Metodi Mladenov is looking for a new team member.
Join our team as an Android Developer and help build the next generation of the A1 XploreTV platform.
Your daily routine would include:
Build and maintain high-performance features for the A1 XploreTV Android TV application and custom STB launcher using Kotlin and Java.
Participate in code reviews, architectural discussions, and hardware-specific optimizations.
We’ll know you can make it if you have:
2+ years of professional Android development experience (experience with Android TV, Fire OS, or STB platforms is a major plus).
Strong proficiency in Kotlin is required, alongside a solid understanding of Java for handling core/legacy platform components.
Team player with strong communication skills who enjoys collaborative problem-solving.
Performance-oriented mindset—you care about frames-per-second, memory footprints, and network efficiency.
Fluent in English (written and spoken).
Our gratitude for the job done will be eternal, but we’ll also offer you:
Innovative technologies and platforms to “play” with.
Attractive remuneration package.
Numerous additional goodies, including, but not limited to free A1 services, discounts, health insurance and services, sports center, childcare, team and family events, etc.
Sounds good? Apply now!
Only shortlisted candidates will be contacted."""


def test_a1_sections_survive_the_join_us_drop():
    reqs = extract_requirements(A1)
    texts = " ".join(r["text"].lower() for r in reqs)
    for bad in ("innovative technologies", "remuneration", "goodies", "shortlisted",
                "metodi", "join our team", "telecom"):
        assert bad not in texts, f"leaked: {bad}"
    musts = [r["text"].lower() for r in reqs if r["kind"] == "must"]
    resp = [r["text"].lower() for r in reqs if r["kind"] == "resp"]
    assert any("2+ years" in t for t in musts)              # requirements recovered
    assert any("proficiency in kotlin" in t for t in musts)
    assert any("fluent in english" in t for t in musts)
    assert any("xploretv" in t for t in resp)               # duties classified as resp
    # personality lines are kind="soft" — kept for context, never scored as gaps
    softs = [r["text"].lower() for r in reqs if r["kind"] == "soft"]
    assert any("team player" in t for t in softs)
    assert any("mindset" in t for t in softs)
    assert not any("team player" in t or "mindset" in t for t in musts)


# observed live: Monzo Platform JD — the must header is "We'd love to hear from you if…"
# (trailing ELLIPSIS + a phrasing missing from the dictionary), so ALL 20 items landed as
# resp -> zero scoring weight -> blind 60% card (owner report)
MONZO_PLATFORM = """The role:
Working hands-on with our Kubernetes clusters, AWS infrastructure, and configuration.
Designing and implementing backend services (APIs, controllers, etc.) that make our platform tick.
We’d love to hear from you if…
You have experience with Kubernetes and AWS in production.
You have strong Go or similar backend language experience.
You care deeply about reliability and observability."""


def test_ellipsis_must_header_recognised():
    reqs = extract_requirements(MONZO_PLATFORM)
    musts = [r["text"].lower() for r in reqs if r["kind"] == "must"]
    resp = [r["text"].lower() for r in reqs if r["kind"] == "resp"]
    assert any("kubernetes and aws in production" in t for t in musts)
    assert any("go or similar" in t for t in musts)
    assert any("kubernetes clusters" in t for t in resp)     # duties stay resp
    # "You care deeply about reliability and observability" is an ATTITUDE, not a checkable
    # requirement — there is nothing in a profile to weigh it against, so it must not be a gap.
    soft = [r["text"].lower() for r in reqs if r["kind"] == "soft"]
    assert any("care deeply about reliability" in t for t in soft)
    assert len(musts) == 2


def test_we_are_looking_for_with_signal_survives():
    # marketing-shaped opener that actually states a qualification must survive
    reqs = extract_requirements("We are looking for someone with 5+ years of Kotlin experience.")
    assert any("kotlin" in r["text"].lower() for r in reqs)


def test_bare_bullet_list_without_header_still_works():
    # pasting just a bullet list (no "Requirements:" header) must keep working
    reqs = extract_requirements("- Kotlin and Jetpack Compose\n- CI/CD pipelines")
    assert len(reqs) == 2 and all(r["kind"] == "must" for r in reqs)


def test_multilingual_drop_headers_skip_boilerplate():
    # A posting in any of the source languages: the OFFER / DATA-PROTECTION section headers are
    # recognised in the posting's own language, so benefits + privacy footers never leak into the
    # requirements — while the bulleted requirements above them are still captured.
    de = ("Anforderungen:\n- Mehrjaehrige Erfahrung mit Python\n- Kenntnisse in Machine Learning\n"
          "Wir bieten:\n- 30 Tage Urlaub\n- Betriebliche Altersvorsorge\n"
          "Datenschutz:\n- Mit Ihrer Bewerbung stimmen Sie der Verarbeitung Ihrer Daten zu.")
    fr = ("Profil recherche :\n- 5 ans d'experience en Python\n- Maitrise du machine learning\n"
          "Ce que nous offrons :\n- 25 jours de conges\n"
          "Pourquoi nous rejoindre ?\n- Une equipe passionnee")
    for text in (de, fr):
        reqs = extract_requirements(text)
        joined = " ".join(r["text"].lower() for r in reqs)
        assert any("python" in r["text"].lower() for r in reqs)          # real reqs kept
        assert "urlaub" not in joined and "conges" not in joined          # benefits skipped
        assert "datenschutz" not in joined and "bewerbung" not in joined  # privacy skipped
        assert "passionnee" not in joined                                 # culture skipped


def test_what_to_expect_section_is_responsibilities_not_requirements():
    # "What to expect:" heads the duties block; those lines must NOT show up as gap requirements
    # (real dev.bg posting: Accedia Junior Mobile Developer put duties in the must bucket).
    jd = ("What are we looking for?\n"
          "We are looking for a mobile developer who is eager to learn.\n"
          "What to expect:\n"
          "Work in a supportive environment for international clients.\n"
          "Work closely with developers of various seniority and analyze requirements.\n"
          "Actively communicate tasks and open questions with your team.\n"
          "Requirements\n"
          "At least 1 year of experience with Kotlin and/or Swift.\n"
          "Good understanding of mobile UI design.\n"
          "Fluency in English.")
    reqs = extract_requirements(jd)
    resp = [r["text"].lower() for r in reqs if r["kind"] == "resp"]
    gaps = [r["text"].lower() for r in reqs if r["kind"] in ("must", "nice")]
    assert any("work closely with developers" in t for t in resp)      # duty -> resp
    assert any("actively communicate" in t for t in resp)
    assert not any("supportive environment" in t for t in gaps)         # not a gap requirement
    assert not any("work closely" in t for t in gaps)
    assert any("kotlin" in t for t in gaps)                             # real requirement stays


def test_multilingual_legal_terms_and_soft_are_not_gaps():
    """Postings arrive in any source language. The consent footer, the terms of employment and
    the personal-quality lines must never become gap requirements — even when they are plain
    bullets with no recognisable section header (which is when the drop-headers can't help)."""
    cases = [
        # (text, the substring of the ONE real requirement)
        ("Anforderungen:\n- Erfahrung mit Python\n"
         "- Mit Ihrer Bewerbung stimmen Sie der Verarbeitung Ihrer personenbezogenen Daten zu.\n"
         "- 40 Wochenstunden, unbefristeter Arbeitsvertrag\n"
         "- Zuverlaessigkeit und Verantwortungsbewusstsein", "python"),
        ("Profil recherche :\n- Experience en Python\n"
         "- En postulant, vous acceptez le traitement de vos donnees personnelles.\n"
         "- 35 heures par semaine, contrat a duree indeterminee\n"
         "- Rigueur et sens des responsabilites", "python"),
        ("Requisitos:\n- Experiencia con Python\n"
         "- Al inscribirte aceptas el tratamiento de tus datos personales.\n"
         "- Trabajo en equipo y proactividad", "python"),
        ("Wymagania:\n- Doswiadczenie z Python\n"
         "- 40 godzin tygodniowo, umowa o prace na czas nieokreslony\n"
         "- Komunikatywnosc i samodzielnosc", "python"),
        ("Requisiti:\n- Esperienza con Python\n"
         "- Affidabilita e senso di responsabilita\n"
         "- Capacita di lavorare in team", "python"),
    ]
    for text, real in cases:
        gaps = [r["text"].lower() for r in extract_requirements(text)
                if r["kind"] in ("must", "nice")]
        assert any(real in g for g in gaps), f"lost the real requirement in: {text[:30]}"
        assert len(gaps) == 1, f"boilerplate leaked into gaps: {gaps}"


def test_third_person_offer_header_and_inline_labels():
    """Real dev.bg agency posting (Cadabra): the perks sat under 'In Return, They Offer:' —
    unrecognised, so the whole block scored as requirements. Plus sub-headers inside a
    requirements block became gap items, and an inline 'Nice to have:' scored as a must."""
    jd = ("Requirements:\n"
          "7+ years of hands-on development experience.\n"
          "Required Experience\n"
          "3+ years with Python.\n"
          "Nice to have: Our cloud platform (GCP, Vertex AI); data versioning (DVC).\n"
          "In Return, They Offer:\n"
          "30 days vacation + 5 additional days for learning and development.\n"
          "Share incentivization plan.\n"
          "Career Enhancement plan.\n"
          "Workshops, Conferences, Hackatons, Tech Deep Dives (internal & external).\n")
    reqs = extract_requirements(jd)
    joined = " ".join(r["text"].lower() for r in reqs)
    for perk in ("vacation", "incentivization", "career enhancement", "hackaton"):
        assert perk not in joined, f"perk leaked: {perk}"
    assert "required experience" not in joined          # a sub-header, not a requirement
    musts = [r["text"].lower() for r in reqs if r["kind"] == "must"]
    nices = [r["text"].lower() for r in reqs if r["kind"] == "nice"]
    assert any("python" in t for t in musts)
    assert any("gcp" in t for t in nices)               # inline label -> nice, and it survives


def test_sentences_are_not_split_on_abbreviations():
    long_line = ("Requirements:\n"
                 "Practical experience using AI-assisted development tools (e.g. Claude Code, "
                 "Codex) across coding, CI, and testing is expected of every engineer here.\n")
    texts = [r["text"] for r in extract_requirements(long_line)]
    assert any("e.g. Claude Code, Codex" in t for t in texts), texts
