"""Scoring quality: a thorough job ad must not lose to a sparse one, and an on-target role must
not sink below its semantic similarity just because a narrow profile can't name every requirement."""
from app.domain.scoring import score, coverage_ratio


def test_missing_nice_to_haves_do_not_sink_the_score():
    # 1 must (covered) + many nice-to-haves the profile doesn't have -> coverage is must-driven,
    # not dragged down by breadth (the detailed-JD-vs-sparse-JD fairness fix)
    reqs = [{"text": "Kotlin", "kind": "must", "skills": ["kotlin"], "weight": 4}]
    reqs += [{"text": f"nice {i}", "kind": "nice", "skills": [f"toolx{i}"], "weight": 3}
             for i in range(12)]
    sc, cov, mis = score("Android · Kotlin", "role", reqs)     # kw-only (no vectors)
    assert sc >= 90 and len(mis) == 12                          # must fully covered -> stays high


def test_covered_nice_to_haves_add_a_bounded_bonus():
    must = [{"text": "Kotlin", "kind": "must", "skills": ["kotlin"], "weight": 4}]
    none = must + [{"text": "CI", "kind": "nice", "skills": ["jenkins"], "weight": 3}]
    withn = must + [{"text": "Git", "kind": "nice", "skills": ["git"], "weight": 3}]
    s_none = score("Android · Kotlin", "role", none)[0]
    s_with = score("Android · Kotlin, Git", "role", withn)[0]
    assert s_with >= s_none                                     # covered nice -> not lower


def _sem_vecs():
    # cosine ~0.86 -> semantic_pct ~0.75 after the 0.6..0.95 rescale
    return [1.0, 0.0], [0.85, 0.5]


def test_role_match_floor_lifts_on_target_role_with_low_coverage():
    # nine must-haves the profile can't name (narrow profile vs thorough JD) + strong semantic
    reqs = [{"text": f"req {i}", "kind": "must", "skills": [f"toolz{i}"], "weight": 4}
            for i in range(9)]
    pv, sv = _sem_vecs()
    off = score("Android Developer", "Senior Android Engineer", reqs,
                profile_vec=pv, posting_vec=sv, role_match=False)[0]
    on = score("Android Developer", "Senior Android Engineer", reqs,
               profile_vec=pv, posting_vec=sv, role_match=True, role_match_floor=0.9)[0]
    assert on > off                                            # the floor helps the on-target role
    assert on >= 65                                            # ~0.9 * 0.75 semantic -> visible


def test_role_match_floor_helps_snippet_without_requirements():
    # a truncated aggregator snippet: no requirements at all -> normally capped at 60%
    pv, sv = _sem_vecs()
    capped = score("Android Developer", "Android Developer", None,
                   profile_vec=pv, posting_vec=sv, role_match=False)[0]
    floored = score("Android Developer", "Android Developer", None,
                    profile_vec=pv, posting_vec=sv, role_match=True, role_match_floor=0.9)[0]
    assert capped <= 60 and floored > capped                   # floor beats the no-evidence cap


def test_coverage_ratio_matches_score_shape():
    # the verifier's recompute is must-driven too, so it can't drift from score()
    pairs = [({"text": "Kotlin", "kind": "must", "weight": 4}, True),
             ({"text": "n1", "kind": "nice", "weight": 3}, False),
             ({"text": "n2", "kind": "nice", "weight": 3}, False)]
    assert coverage_ratio(pairs) == 1.0                        # must covered; missing nice ignored
