"""Hard filters: seniority (management/IC, junior/senior), location and geo compatibility."""
from app.domain.filters import geo_ok, location_ok, seniority_ok, passes_hard_filters, is_hybrid


class P:
    """Minimal profile stand-in."""
    def __init__(self, target_roles="Android", experience="", remote_pref="remote",
                 location_pref="Remote / Varna", country="Bulgaria", relocate=False):
        self.target_roles = target_roles
        self.experience = experience
        self.remote_pref = remote_pref
        self.location_pref = location_pref
        self.country = country
        self.relocate = relocate


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


def test_remote_with_no_preferred_cities_drops_onsite():
    # remote candidate who gave no cities can't take an onsite role
    assert location_ok(P(remote_pref="remote", location_pref=""), "Bangalore, India") is False
    assert location_ok(P(remote_pref="remote", location_pref=""), "Remote, India") is True
    # an onsite-seeking candidate with no city given: we can't judge, keep it
    assert location_ok(P(remote_pref="onsite", location_pref=""), "Bangalore, India") is True


# ---- combined ----
def test_passes_hard_filters_reasons():
    ic_remote = P(target_roles="Android", remote_pref="remote", location_pref="Remote / Varna")
    ok, reason = passes_hard_filters(ic_remote, "Engineering Manager", "Remote")
    assert ok is False and reason == "seniority"
    ok, reason = passes_hard_filters(ic_remote, "Senior Android Engineer", "San Francisco")
    assert ok is False and reason == "location"
    ok, reason = passes_hard_filters(ic_remote, "Senior Android Engineer", "Remote - EU")
    assert ok is True and reason == ""


# ---- hybrid (owner report: a HYBRID dev.bg posting reached a REMOTE-only filter) ----
def test_is_hybrid_detects_and_respects_full_remote():
    assert is_hybrid("Hybrid role, 2 days a week in the office") is True
    assert is_hybrid("Хибриден модел на работа") is True
    assert is_hybrid("3 days in the office, rest from home") is True
    assert is_hybrid("Fully remote team; we dropped hybrid last year") is False   # full-remote wins
    assert is_hybrid("Remote-first company") is False
    assert is_hybrid("Great engineering culture, strong mentorship") is False     # no signal


def test_remote_profile_drops_hybrid_posting_signalled_in_description():
    # the reported case: dev.bg posting has empty location, "hybrid" only in the description
    ic_remote = P(target_roles="Android", remote_pref="remote", location_pref="")
    ok, reason = passes_hard_filters(
        ic_remote, "Senior Android Developer", "",
        "We work in a hybrid model — 2 days a week in the office in Sofia.")
    assert ok is False and reason == "location"


def test_remote_profile_keeps_posting_offering_full_remote():
    ic_remote = P(target_roles="Android", remote_pref="remote", location_pref="")
    ok, reason = passes_hard_filters(
        ic_remote, "Senior Android Developer", "",
        "Hybrid or fully remote — your choice.")
    assert ok is True and reason == ""


def test_hybrid_ignored_for_non_remote_seekers():
    hybrid_ok = P(target_roles="Android", remote_pref="hybrid", location_pref="")
    ok, _ = passes_hard_filters(hybrid_ok, "Senior Android Developer", "",
                                "Hybrid, 2 days a week in the office.")
    assert ok is True                     # a hybrid seeker is fine with a hybrid posting


# ---- geo restrictions (owner report: "Remote" posting actually required moving to the UK) ----
def test_remote_with_country_restriction_dropped_for_non_relocator():
    assert geo_ok(P(), "Remote - UK") is False
    assert geo_ok(P(), "[Remote] Dallas, Texas") is False
    assert geo_ok(P(), "Remote", "You must be based in the United Kingdom.") is False
    assert geo_ok(P(), "Remote", "Candidates must be eligible to work in the US.") is False


def test_relocator_sees_everything():
    assert geo_ok(P(relocate=True), "Remote - UK") is True
    assert geo_ok(P(relocate=True), "London, United Kingdom",
                  "Relocation to the UK required.") is True


def test_plain_remote_and_own_country_pass():
    assert geo_ok(P(), "Remote") is True
    assert geo_ok(P(), "Sofia, Bulgaria") is True
    assert geo_ok(P(), "Remote", "We are a distributed team.") is True


def test_eu_wide_remote_passes_for_eu_resident():
    assert geo_ok(P(), "Remote (EU)") is True
    assert geo_ok(P(), "Remote", "You can work remotely from anywhere in Europe.") is True
    # ...but a UK-only restriction is not EU
    assert geo_ok(P(), "Remote - UK only") is False


def test_mere_mention_in_description_is_not_a_restriction():
    assert geo_ok(P(), "Remote", "Our clients are leading banks in Germany and France.") is True
    assert geo_ok(P(), "Remote", "The user experience is our priority.") is True   # 'the us'!


def test_relocation_required_dropped_unless_willing():
    # unknown destination -> you'd still have to move -> drop
    assert geo_ok(P(), "Remote", "Relocation is required for this role.") is False
    # destination is the candidate's own country -> a city move, location_ok's business
    assert geo_ok(P(), "Sofia, Bulgaria", "Relocation is required for this role.") is True
    assert geo_ok(P(relocate=True), "Remote", "Willingness to relocate is expected.") is True


def test_passes_hard_filters_reports_geo_as_location():
    ok, reason = passes_hard_filters(P(), "Android Developer", "Remote - UK", "desc")
    assert ok is False and reason == "location"
