"""Role-family compatibility (Phase 6): hard drop for a different discipline, soft for adjacent."""
from app.domain.role_family import (families, conflict, role_family_ok, role_family_factor)
from app.domain.filters import passes_hard_filters


class _Prof:
    def __init__(self, target_roles="", remote_pref="any", location_pref="", country="Bulgaria"):
        self.target_roles = target_roles
        self.remote_pref, self.location_pref, self.country = remote_pref, location_pref, country
        self.relocate = False
        self.experience = ""


# ---- android vs ios ----
def test_ios_is_a_hard_mismatch_for_android():
    assert families("iOS Developer") == {"ios"}
    assert families("Android Developer") == {"android"}
    assert conflict(families("Android Developer"), families("iOS Developer")) == "hard"
    assert role_family_ok(_Prof(target_roles="Android Developer"), "iOS Developer - София") is False
    ok, reason = passes_hard_filters(_Prof(target_roles="Android Developer"),
                                     "iOS Developer - София", "София", "")
    assert ok is False and reason == "role"


def test_cross_platform_matches_both_specialists():
    # React Native / Flutter / KMP / generic "Mobile Developer" carry BOTH families
    for title in ("React Native Developer", "Flutter Developer", "Kotlin Multiplatform Developer",
                  "Mobile Developer"):
        assert {"android", "ios"} <= families(title)
        assert role_family_ok(_Prof(target_roles="Android Developer"), title) is True
        assert role_family_ok(_Prof(target_roles="iOS Engineer"), title) is True


# ---- family detection ----
def test_families_from_specific_cues():
    assert families("Backend Developer") == {"backend"}
    assert families("Senior QA Engineer") == {"qa"}
    assert families("Data Scientist") == {"data_science"}
    # full-stack counts as both halves, so it never conflicts with backend or frontend
    assert families("Full Stack Engineer") == {"fullstack", "backend", "frontend"}


def test_bare_title_names_no_family():
    # 'Software Engineer' / 'Developer' are deliberately family-less -> never judged
    assert families("Software Engineer") == frozenset()
    assert families("Developer") == frozenset()
    assert families("") == frozenset()


def test_cue_needs_word_boundary():
    # 'sre' must not fire inside 'stores'; 'etl' not inside 'metalworker'
    assert "devops" not in families("Retail stores associate")
    assert families("Kiosk attendant") == frozenset()      # no 'ios' match inside 'kiosk'


# ---- conflict classification ----
def test_conflict_levels():
    assert conflict(families("Backend"), families("Backend Engineer")) == "none"     # overlap
    assert conflict(families("Backend"), families("Software Engineer")) == "none"     # undecidable
    assert conflict(families("Data Scientist"), families("Data Engineer")) == "soft"  # adjacent
    assert conflict(families("Backend"), families("QA Engineer")) == "hard"           # different


# ---- hard filter ----
def test_hard_filter_drops_cross_discipline():
    p = _Prof(target_roles="Backend Developer")
    ok, reason = passes_hard_filters(p, "Senior QA Automation Engineer", "Remote", "")
    assert ok is False and reason == "role"


def test_hard_filter_keeps_adjacent_and_undecidable():
    p = _Prof(target_roles="Data Scientist")
    # adjacent (data engineer) is not dropped — it's soft-weighted instead
    assert passes_hard_filters(p, "Senior Data Engineer", "Remote", "")[0] is True
    # a bare 'Software Engineer' posting names no family -> never dropped on role grounds
    assert passes_hard_filters(p, "Software Engineer", "Remote", "")[0] is True
    # profile with no concrete family never triggers a role drop
    assert passes_hard_filters(_Prof(target_roles="Engineer"), "QA Engineer", "Remote", "")[0] is True


# ---- soft factor ----
def test_soft_factor_only_on_adjacent():
    p = _Prof(target_roles="Data Scientist")
    assert role_family_factor(p, "Data Engineer", adjacent=0.8) == 0.8      # adjacent -> penalty
    assert role_family_factor(p, "Data Scientist", adjacent=0.8) == 1.0     # same family -> none
    assert role_family_factor(p, "Software Engineer", adjacent=0.8) == 1.0  # undecidable -> none
    # a hard mismatch is dropped by the filter, so the factor stays neutral (never double-counts)
    assert role_family_factor(_Prof(target_roles="Backend"), "QA Engineer", adjacent=0.8) == 1.0


def test_role_family_ok_symmetry():
    # the check is symmetric: a QA candidate should not see a Backend posting either
    assert role_family_ok(_Prof(target_roles="QA Engineer"), "Backend Developer") is False
    assert role_family_ok(_Prof(target_roles="Backend Developer"), "QA Engineer") is False
