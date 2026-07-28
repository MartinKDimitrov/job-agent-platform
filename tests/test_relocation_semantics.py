"""Relocation semantics (Phase 6): work-TYPE is the hard filter; `relocate` only frees up the
GEOGRAPHY. A remote seeker gets remote roles wherever they must live (relocate lets a 'remote,
must reside in Germany' role through via geo_ok) — but a purely on-site role never fits them,
relocate or not. An on-site seeker willing to relocate takes an office role in any city. Plus: a
Match whose posting no longer passes the current hard filters is swept even when its posting fell
out of the recall set."""
from sqlalchemy import select

import app.application.usecases.search as crawl
from app.data.db import SessionLocal
from app.data.models import Match
from app.domain.filters import location_ok, work_type_ok, passes_hard_filters, is_remote
from tests.test_crawl import _make_profile_row
from tests.test_recall import _post


class _Prof:
    def __init__(self, remote_pref="remote", relocate=False, location_pref="", country="Bulgaria"):
        self.remote_pref, self.relocate = remote_pref, relocate
        self.location_pref, self.country = location_pref, country
        self.target_roles = "Backend Developer"
        self.experience = ""


_ONSITE_DE = "Berlin, Germany"


# ---- work-type is the hard filter; relocate does NOT unlock on-site for a remote seeker ----
def test_remote_seeker_never_takes_onsite_even_with_relocate():
    # work-TYPE is independent of relocate: a remote seeker never takes a purely on-site role
    assert work_type_ok(_Prof(relocate=False), "t", _ONSITE_DE, "") is False
    assert work_type_ok(_Prof(relocate=True), "t", _ONSITE_DE, "") is False


def test_remote_seeker_keeps_remote_roles():
    assert location_ok(_Prof(relocate=True), "Remote") is True
    assert location_ok(_Prof(relocate=False), "Remote") is True


def test_onsite_in_description_hidden_from_remote_seeker_regardless_of_relocate():
    onsite_desc = "This is an office-based role, no remote."
    for reloc in (False, True):
        ok, reason = passes_hard_filters(_Prof(relocate=reloc), "Backend Developer", "", onsite_desc)
        assert ok is False and reason == "location"


# ---- a remote role reaches a remote seeker even when the location names the employer's city ----
def test_is_remote_detects_role_from_text_and_title():
    assert is_remote("Android Developer", "Berlin, Deutschland",
                     "This is a 100% remote position.") is True
    assert is_remote("Android Developer - Remote", "Warszawa", "Kotlin needed.") is True
    assert is_remote("Android Developer", "Remote", "") is True
    assert is_remote("Android Developer", "Berlin", "On-site role in our office.") is False


def test_remote_role_with_city_location_reaches_remote_seeker():
    # a Berlin company advertising an EU-remote position — location names a city, role is remote
    ok, _ = passes_hard_filters(_Prof(remote_pref="remote", relocate=True),
                                "Android Developer", "Berlin, Deutschland",
                                "A 100% remote position, work from anywhere in the EU.")
    assert ok is True
    ok2, _ = passes_hard_filters(_Prof(remote_pref="remote", relocate=True),
                                 "Android Developer - Remote", "Warszawa", "Kotlin needed.")
    assert ok2 is True


def test_onsite_role_with_city_still_hidden_from_remote_seeker():
    ok, reason = passes_hard_filters(_Prof(remote_pref="remote", relocate=True),
                                     "Android Developer", "Berlin, Deutschland",
                                     "On-site role based in our Berlin office.")
    assert ok is False and reason == "location"


def test_no_remote_phrasing_not_treated_as_remote():
    # 'not a remote position' must NOT slip through as remote
    ok, reason = passes_hard_filters(_Prof(remote_pref="remote", relocate=True),
                                     "Android Developer", "Berlin",
                                     "This is not a remote position — office-based.")
    assert ok is False and reason == "location"


# ---- on-site seeker: symmetric guard — wants an office, in the right city ----
def test_onsite_seeker_excludes_pure_remote_role():
    p = _Prof(remote_pref="onsite")
    assert passes_hard_filters(p, "Android Engineer", "Remote", "")[:2] == (False, "location")
    assert passes_hard_filters(p, "Kotlin Developer", "", "Fully remote position.")[:2] \
        == (False, "location")


def test_onsite_seeker_keeps_hybrid_and_office_roles():
    p = _Prof(remote_pref="onsite")
    assert passes_hard_filters(p, "Android Engineer", "Sofia", "Office-based role.")[0] is True
    assert passes_hard_filters(p, "Android Engineer", "",
                               "Hybrid work, 2 days in the office.")[0] is True


def test_onsite_seeker_with_city_drops_other_city_named_in_text():
    # location_pref=Sofia, the posting is a Plovdiv role stated only in the text (empty location)
    p = _Prof(remote_pref="onsite", location_pref="София")
    assert passes_hard_filters(p, "Senior Android Developer", "",
                               "Flexible hybrid work in Plovdiv, Bulgaria.")[:2] == (False, "location")
    # the preferred city named -> kept
    assert passes_hard_filters(p, "Android Developer", "", "On-site in our Sofia office.")[0] is True
    # no city named at all -> can't tell, kept
    assert passes_hard_filters(p, "Android Developer", "", "Great team, home office option.")[0] is True


# ---- on-site seeker: relocate frees the city ----
def test_onsite_seeker_with_relocate_takes_any_city():
    p = _Prof(remote_pref="onsite", relocate=True, location_pref="Sofia")
    assert location_ok(p, _ONSITE_DE) is True           # willing to move -> a Berlin office is fine
    p2 = _Prof(remote_pref="onsite", relocate=False, location_pref="Sofia")
    assert location_ok(p2, _ONSITE_DE) is False          # not willing -> only Sofia


# ---- zombie sweep (integration) ----
def test_zombie_match_swept_when_posting_fails_current_filter():
    with SessionLocal() as db:
        # an on-site role unrelated to the profile -> it is NOT in the recall set
        zp = _post(db, "Data Entry Clerk", "zomb1", company="Foo")
        zp.location = _ONSITE_DE
        db.commit()
        p = _make_profile_row(db, target_roles="Backend", skills="Python")
        p.remote_pref, p.relocate = "remote", True       # remote seeker -> on-site must not survive
        db.add(Match(profile_id=p.id, posting_id=zp.id, score=90, covered=[], missing=[]))
        db.commit()
        crawl.search_db(db, p)
        assert db.execute(select(Match).where(Match.posting_id == zp.id)).first() is None


def test_valid_out_of_recall_match_is_kept():
    with SessionLocal() as db:
        zp = _post(db, "Data Entry Clerk", "zomb2", company="Foo")
        zp.location = "Remote"                            # still passes the remote filter
        db.commit()
        p = _make_profile_row(db, target_roles="Backend", skills="Python")
        p.remote_pref, p.relocate = "remote", False
        db.add(Match(profile_id=p.id, posting_id=zp.id, score=90, covered=[], missing=[]))
        db.commit()
        crawl.search_db(db, p)
        # out of recall but still valid -> the match survives (recall gap is not a reason to drop)
        assert db.execute(select(Match).where(Match.posting_id == zp.id)).first() is not None
