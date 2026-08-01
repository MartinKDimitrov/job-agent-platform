"""Hermetic tests for the silver-label eval's pure parts (no DB / no model).

The full `run()` needs the staging tunnel + the E5 model, so it isn't unit-tested here (same as
eval_matching); what IS locked down is the relevance oracle and the ranking metrics."""
from app.domain.role_family import families
from app.tools.eval_silver import _average_precision, _recall_at, silver_grade


def test_silver_grade_same_discipline_is_2():
    pf = families("Machine Learning Engineer, AI Engineer")
    assert silver_grade(pf, "Senior Machine Learning Engineer") == 2


def test_silver_grade_unrelated_is_0():
    pf = families("Machine Learning Engineer")
    assert silver_grade(pf, "Concrete Finisher / Construction Worker") == 0


def test_silver_grade_unclassifiable_title_is_0():
    # a title role_family can't place must not count as a match
    pf = families("Machine Learning Engineer")
    assert silver_grade(pf, "Zzzz Qwerty") == 0


def test_average_precision_perfect_ranking():
    # both relevant items ranked first -> AP == 1.0
    assert _average_precision([2, 2, 0, 0], total_relevant=2) == 1.0


def test_average_precision_rewards_earlier_hits():
    early = _average_precision([2, 0, 2, 0], 2)
    late = _average_precision([0, 0, 2, 2], 2)
    assert early > late


def test_recall_at_counts_relevant_in_topk():
    assert _recall_at([2, 0, 2, 0, 2], k=3, total_relevant=4) == 0.5   # 2 of 4 in the top-3


def test_metrics_handle_no_relevant():
    assert _average_precision([0, 0], 0) == 0.0
    assert _recall_at([0, 0], 5, 0) == 0.0
