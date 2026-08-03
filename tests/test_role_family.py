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


# ---- backend/Java roles must NOT surface for a mobile profile (owner tightening) ----
def test_backend_language_titles_get_the_backend_family():
    # server-stack titles that never say "backend" are still classified as backend
    for title in ("Java Developer", "Java Software Engineer", "Spring Boot Developer",
                  ".NET Developer", "C# Developer", "Golang Developer", "Backend Developer - Node.js"):
        assert families(title) == {"backend"}, title


def test_backend_is_a_hard_mismatch_for_android():
    p = _Prof(target_roles="Android Developer")
    assert conflict(families("Android Developer"), families("Java Developer")) == "hard"
    for title in ("Java Software Engineer", "Senior Java Developer", "Spring Boot Developer",
                  "Backend Developer"):
        assert role_family_ok(p, title) is False, title
        assert passes_hard_filters(p, title, "Remote", "")[:2] == (False, "role"), title


def test_android_plus_backend_hybrid_still_matches():
    # a title carrying BOTH families overlaps the profile -> kept (it IS an Android role)
    p = _Prof(target_roles="Android Developer")
    assert families("Android Developer with Java Backend Experience") == {"android", "backend"}
    assert role_family_ok(p, "Android Developer with Java Backend Experience") is True
    # a bare "Java/Kotlin Developer" stays family-less (undecidable) -> not dropped
    assert families("Java/Kotlin Developer") == frozenset()


def test_backend_still_adjacent_for_ml_and_data():
    # tightening android↔backend must NOT touch the other backend adjacencies
    assert conflict(families("Machine Learning Engineer"), families("Java Developer")) == "soft"
    assert role_family_ok(_Prof(target_roles="Machine Learning Engineer"), "Backend Developer") is True


# ---- non-tech verticals (ESCO pilot): classified, and hard-mismatched across disciplines ----
def test_non_tech_families_detected():
    assert families("Tax Accountant") == {"finance"}
    assert families("Registered Nurse") == {"nursing"}   # healthcare split into sub-professions
    assert families("Sales Representative") == {"sales"}
    assert families("Brand Manager") == {"marketing"}
    # a bare "Manager" / "Specialist" still names no family (conservative)
    assert families("Manager") == frozenset()


def test_accountant_keeps_finance_drops_other_disciplines():
    p = _Prof(target_roles="bookkeeper, accountant, счетоводител")
    assert families(p.target_roles) == {"finance"}
    for keep in ("Operational Accountant", "Financial Controller", "Financial Analyst", "Auditor"):
        assert role_family_ok(p, keep) is True, keep
    for drop in ("Android Developer", "Backend Engineer", "Registered Nurse", "Sales Representative"):
        assert role_family_ok(p, drop) is False, drop
        assert passes_hard_filters(p, drop, "Remote", "")[:2] == (False, "role"), drop


def test_it_profile_does_not_match_non_tech_and_vice_versa():
    assert role_family_ok(_Prof(target_roles="Android Developer"), "Tax Accountant") is False
    assert role_family_ok(_Prof(target_roles="Registered Nurse"), "Backend Developer") is False
    # sales and marketing overlap -> adjacent (soft), still shown
    assert conflict(families("Sales Representative"), families("Marketing Manager")) == "soft"
