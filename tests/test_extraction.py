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
