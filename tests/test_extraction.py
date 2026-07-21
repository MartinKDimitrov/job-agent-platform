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


def test_we_are_looking_for_with_signal_survives():
    # marketing-shaped opener that actually states a qualification must survive
    reqs = extract_requirements("We are looking for someone with 5+ years of Kotlin experience.")
    assert any("kotlin" in r["text"].lower() for r in reqs)


def test_bare_bullet_list_without_header_still_works():
    # pasting just a bullet list (no "Requirements:" header) must keep working
    reqs = extract_requirements("- Kotlin and Jetpack Compose\n- CI/CD pipelines")
    assert len(reqs) == 2 and all(r["kind"] == "must" for r in reqs)
