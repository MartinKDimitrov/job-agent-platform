"""Filter regression MATRIX — the whole hard-filter + geography model across every combination of
work-TYPE preference, relocate flag, a named city vs none, and each posting shape.

The point is stability: change a filter, run this, and see immediately whether a combination broke.
It is deliberately exhaustive on the *shapes* (remote / preferred-city / other-city-same-country /
other-country / hybrid / unknown / EU-remote-with-city / mislabelled-remote) rather than on real
place names — one representative city per role suffices.

Each row asserts the outcome of passes_hard_filters (pass + reason) and, when it passes,
location_factor (1.0 preferred/remote/unknown · 0.8 a place the candidate would only relocate to).
"""
import pytest

from app.domain.filters import passes_hard_filters, location_factor

# candidate lives in Germany; when a city is named it is Berlin.
_CITY = "Berlin"
_COUNTRY = "Germany"
_TITLE = "Android Developer"          # matches the target role (no role-family / seniority noise)


class _P:
    def __init__(self, remote_pref, relocate, location_pref):
        self.target_roles = "Android Developer"
        self.experience = ""
        self.remote_pref = remote_pref
        self.relocate = relocate
        self.location_pref = location_pref
        self.country = _COUNTRY


# posting shapes: (loc, description) — all within Germany or remote, so geo_ok (country/visa) never
# interferes; the geography axis here is purely the CITY preference.
SHAPES = {
    "remote":        ("Remote", ""),
    "pref_city":     ("Berlin, Germany", ""),
    "other_city":    ("Munich, Germany", ""),                 # different city, same country
    "hybrid":        ("", "Hybrid work, 2 days a week in the office."),
    "unknown":       ("", "Great team building products with Kotlin."),
    "eu_remote_city": ("Berlin, Germany", "A 100% remote position, work from anywhere in the EU."),
    "mislabelled":   ("Remote", "This is NOT a remote position — office-based."),
}

# (id, remote_pref, relocate, location_pref, shape, want_pass, want_reason, want_factor)
# want_factor is only checked when want_pass is True.
CASES = [
    # ---------- remote seeker, city named ----------
    ("rem_city_remote",  "remote", False, _CITY, "remote",         True,  "",         1.0),
    ("rem_city_pref",    "remote", False, _CITY, "pref_city",      True,  "",         1.0),  # named city, onsite ok
    ("rem_city_other",   "remote", False, _CITY, "other_city",     False, "location", None), # remote won't do onsite elsewhere
    ("rem_city_hybrid",  "remote", False, _CITY, "hybrid",         False, "location", None),
    ("rem_city_unknown", "remote", False, _CITY, "unknown",        True,  "",         1.0),
    ("rem_city_eurem",   "remote", False, _CITY, "eu_remote_city", True,  "",         1.0),
    ("rem_city_mislbl",  "remote", False, _CITY, "mislabelled",    False, "location", None),
    # relocate does NOT change work-TYPE for a remote seeker
    ("rem_city_other_reloc", "remote", True, _CITY, "other_city",  False, "location", None),

    # ---------- remote seeker, no city ----------
    ("rem_nocity_remote", "remote", False, "", "remote",   True,  "",         1.0),
    ("rem_nocity_pref",   "remote", False, "", "pref_city", False, "location", None),  # onsite, no named city
    ("rem_nocity_unknown","remote", False, "", "unknown",  True,  "",         1.0),

    # ---------- on-site seeker, city named ----------
    ("on_city_remote",  "onsite", False, _CITY, "remote",        False, "location", None), # onsite rejects remote
    ("on_city_pref",    "onsite", False, _CITY, "pref_city",     True,  "",         1.0),
    ("on_city_other_F", "onsite", False, _CITY, "other_city",    False, "location", None), # no relocate -> drop
    ("on_city_other_T", "onsite", True,  _CITY, "other_city",    True,  "",         0.8),  # relocate -> secondary
    ("on_city_hybrid",  "onsite", False, _CITY, "hybrid",        False, "location", None),  # office days but city unconfirmed
    ("on_city_unknown", "onsite", False, _CITY, "unknown",       False, "location", None),  # can't confirm the city
    ("on_city_eurem",   "onsite", False, _CITY, "eu_remote_city", False, "location", None), # fully-remote -> no office

    # ---------- on-site seeker, no city ----------
    ("on_nocity_remote",  "onsite", False, "", "remote",     False, "location", None),
    ("on_nocity_pref",    "onsite", False, "", "pref_city",  True,  "",         1.0),      # any city ok (none named)
    ("on_nocity_other",   "onsite", False, "", "other_city", True,  "",         1.0),      # no pref -> not 'elsewhere'
    ("on_nocity_unknown", "onsite", False, "", "unknown",    True,  "",         1.0),

    # ---------- hybrid seeker ----------
    ("hyb_city_remote", "hybrid", False, _CITY, "remote",     True,  "", 1.0),
    ("hyb_city_hybrid", "hybrid", False, _CITY, "hybrid",     True,  "", 1.0),
    ("hyb_city_pref",   "hybrid", False, _CITY, "pref_city",  True,  "", 1.0),
    ("hyb_city_other_F","hybrid", False, _CITY, "other_city", False, "location", None),
    ("hyb_city_other_T","hybrid", True,  _CITY, "other_city", True,  "", 0.8),

    # ---------- 'any' work type: geography still applies when a city is named ----------
    ("any_city_remote", "any", False, _CITY, "remote",     True,  "", 1.0),
    ("any_city_pref",   "any", False, _CITY, "pref_city",  True,  "", 1.0),
    ("any_city_other_F","any", False, _CITY, "other_city", False, "location", None),
    ("any_city_other_T","any", True,  _CITY, "other_city", True,  "", 0.8),
    ("any_city_unknown","any", False, _CITY, "unknown",    True,  "", 1.0),
    # 'any' with no city -> everything passes geography
    ("any_nocity_other","any", False, "", "other_city", True,  "", 1.0),
    ("any_nocity_remote","any", False, "", "remote",     True,  "", 1.0),
]


@pytest.mark.parametrize("cid,pref,reloc,locpref,shape,want_pass,want_reason,want_factor",
                         CASES, ids=[c[0] for c in CASES])
def test_filter_matrix(cid, pref, reloc, locpref, shape, want_pass, want_reason, want_factor):
    p = _P(pref, reloc, locpref)
    loc, desc = SHAPES[shape]
    ok, reason = passes_hard_filters(p, _TITLE, loc, desc)
    assert ok is want_pass, f"{cid}: pass expected {want_pass}, got {ok} (reason {reason!r})"
    if not want_pass:
        assert reason == want_reason, f"{cid}: reason expected {want_reason!r}, got {reason!r}"
    else:
        f = location_factor(p, _TITLE, loc, desc)
        assert f == want_factor, f"{cid}: location_factor expected {want_factor}, got {f}"


# ---- geography vs country ELIGIBILITY (geo_ok) — a couple of representative cross-country rows ----
def test_other_country_needs_relocate():
    # candidate in Germany, no city named; an on-site role in another country
    p = _P("onsite", relocate=False, location_pref="")
    ok, reason = passes_hard_filters(p, _TITLE, "Warsaw, Poland", "")
    assert ok is False and reason == "location"          # geo_ok: different country, won't relocate
    p2 = _P("onsite", relocate=True, location_pref="")
    assert passes_hard_filters(p2, _TITLE, "Warsaw, Poland", "")[0] is True   # relocate frees country


def test_remote_role_ignores_country_restriction_when_relocating():
    p = _P("remote", relocate=True, location_pref="")
    # a remote role that names a foreign city in its text still reaches a relocating remote seeker
    ok, _ = passes_hard_filters(p, "Android Developer",
                                "Warsaw, Poland", "Fully remote, work from anywhere in the EU.")
    assert ok is True


# ---- the other hard filters still compose in the matrix world ----
def test_role_and_seniority_still_apply():
    p = _P("onsite", relocate=True, location_pref=_CITY)
    # iOS role for an Android profile -> role mismatch even in the preferred city
    assert passes_hard_filters(p, "iOS Developer", "Berlin, Germany", "")[:2] == (False, "role")
    # a management role for an IC -> seniority
    assert passes_hard_filters(p, "Engineering Manager", "Berlin, Germany", "")[:2] \
        == (False, "seniority")
