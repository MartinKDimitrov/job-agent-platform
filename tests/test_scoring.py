"""Tests for match scoring.

The `no_embeddings` autouse fixture forces the weighted-keyword path, so these assert the
scoring *logic* (weighting, covered/missing, legacy shapes) deterministically without a model.
"""
from app.domain.scoring import score


def test_covered_and_missing_shapes():
    reqs = [{"text": "Kotlin", "kind": "must"}, {"text": "Rust", "kind": "must"}]
    sc, covered, missing = score("expert in kotlin", "kotlin role", reqs)
    assert [c["text"] for c in covered] == ["Kotlin"]
    assert [m["text"] for m in missing] == ["Rust"]
    assert 0 <= sc <= 100


def test_must_have_weighted_higher_than_nice():
    profile = "kotlin developer"
    # Covering a must-have should score higher than covering only a nice-to-have.
    must_reqs = [{"text": "Kotlin", "kind": "must"}, {"text": "Rust", "kind": "nice"}]
    nice_reqs = [{"text": "Rust", "kind": "must"}, {"text": "Kotlin", "kind": "nice"}]
    sc_must, _, _ = score(profile, "role", must_reqs)
    sc_nice, _, _ = score(profile, "role", nice_reqs)
    assert sc_must > sc_nice


def test_responsibilities_not_scored_as_gaps():
    # A responsibility the profile doesn't mention must not drag the score down.
    with_resp = [{"text": "Kotlin", "kind": "must"},
                 {"text": "lead a team of twenty", "kind": "resp"}]
    without = [{"text": "Kotlin", "kind": "must"}]
    assert score("kotlin", "r", with_resp)[0] == score("kotlin", "r", without)[0]


def test_soft_skills_not_scored_as_gaps():
    # Personality lines (team player, mindset...) must not drag the score down.
    with_soft = [{"text": "Kotlin", "kind": "must"},
                 {"text": "Team player with strong communication skills", "kind": "soft"}]
    without = [{"text": "Kotlin", "kind": "must"}]
    assert score("kotlin", "r", with_soft)[0] == score("kotlin", "r", without)[0]


def test_english_level_covers_language_requirement():
    # Profile.as_text carries "English B2", so 'Fluent in English' counts as covered.
    from app.data.models import Profile
    p = Profile(name="x", skills="Kotlin", english_level="B2")
    reqs = [{"text": "Fluent in English (written and spoken)", "kind": "must"}]
    _, covered, missing = score(p.as_text(), "role", reqs)
    assert [c["text"] for c in covered] == [reqs[0]["text"]] and missing == []


def test_legacy_string_requirements_supported():
    # Older rows stored requirements as plain strings — must still work.
    sc, covered, missing = score("kotlin expert", "role", ["Kotlin", "Rust"])
    assert {c["text"] for c in covered} == {"Kotlin"}
    assert {m["text"] for m in missing} == {"Rust"}


def test_no_requirements_keyword_only():
    # With no requirements and no embeddings, there is nothing to score -> 0.
    sc, covered, missing = score("kotlin", "role", [])
    assert sc == 0 and covered == [] and missing == []


def test_no_requirements_semantic_only_is_capped():
    # If the extractor found nothing, similarity alone must never claim above 60% —
    # an "86% with 0 covered" ring destroys score credibility (observed on staging).
    import app.domain.scoring as scoring
    orig = scoring.embed
    scoring.embed = lambda text: [1.0, 0.0]      # perfect similarity
    try:
        sc, covered, missing = score("kotlin", "kotlin role", [])
        assert covered == [] and missing == []
        assert sc <= 60
    finally:
        scoring.embed = orig


def test_full_coverage_scores_high():
    reqs = [{"text": "Kotlin", "kind": "must"}, {"text": "Compose", "kind": "must"}]
    sc, _, missing = score("kotlin and compose", "role", reqs)
    assert missing == [] and sc == 100
