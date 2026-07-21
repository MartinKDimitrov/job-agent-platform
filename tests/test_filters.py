"""Hard filters: seniority (management/IC, junior/senior) and location compatibility."""
from app.filters import location_ok, seniority_ok, passes_hard_filters


class P:
    """Minimal profile stand-in."""
    def __init__(self, target_roles="Android", experience="", remote_pref="remote",
                 location_pref="Remote / Varna"):
        self.target_roles = target_roles
        self.experience = experience
        self.remote_pref = remote_pref
        self.location_pref = location_pref


# ---- seniority ----
def test_management_role_filtered_for_ic_profile():
    assert seniority_ok(P(target_roles="Android"), "Engineering Manager, Mobile") is False
    assert seniority_ok(P(target_roles="Android"), "Director of Engineering") is False


def test_management_role_passes_when_profile_wants_management():
    assert seniority_ok(P(target_roles="Android Team Lead"), "Engineering Manager") is True
    assert seniority_ok(P(target_roles="Engineering Manager"), "Engineering Manager") is True


def test_ic_roles_pass():
    ic = P(target_roles="Android")
    assert seniority_ok(ic, "Senior Android Engineer") is True
    assert seniority_ok(ic, "Android Developer") is True
    assert seniority_ok(ic, "Staff Android Engineer") is True     # staff = senior IC, not mgmt
    assert seniority_ok(ic, "Tech Lead, Android") is True         # tech lead = IC, not mgmt


def test_junior_role_filtered_for_senior_profile():
    assert seniority_ok(P(target_roles="Senior Android"), "Junior Android Engineer") is False
    # but fine for a non-senior profile
    assert seniority_ok(P(target_roles="Android"), "Junior Android Engineer") is True


# ---- location ----
def test_remote_profile_accepts_remote_posting():
    assert location_ok(P(remote_pref="remote"), "Remote - EU") is True
    assert location_ok(P(remote_pref="remote"), "Anywhere") is True


def test_remote_profile_rejects_unrelated_onsite():
    assert location_ok(P(remote_pref="remote", location_pref="Remote / Varna"),
                       "San Francisco, CA") is False
    assert location_ok(P(remote_pref="remote", location_pref="Remote / Varna"),
                       "London, UK") is False


def test_remote_profile_accepts_preferred_onsite_city():
    assert location_ok(P(remote_pref="remote", location_pref="Remote / Varna"),
                       "Varna, Bulgaria") is True


def test_any_pref_and_unknown_location_pass():
    assert location_ok(P(remote_pref="any"), "San Francisco") is True
    assert location_ok(P(remote_pref="remote"), "") is True       # unknown -> don't hide


# ---- combined ----
def test_passes_hard_filters_reasons():
    ic_remote = P(target_roles="Android", remote_pref="remote", location_pref="Remote / Varna")
    ok, reason = passes_hard_filters(ic_remote, "Engineering Manager", "Remote")
    assert ok is False and reason == "seniority"
    ok, reason = passes_hard_filters(ic_remote, "Senior Android Engineer", "San Francisco")
    assert ok is False and reason == "location"
    ok, reason = passes_hard_filters(ic_remote, "Senior Android Engineer", "Remote - EU")
    assert ok is True and reason == ""
