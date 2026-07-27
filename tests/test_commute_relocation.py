"""Relocation + commute (Phase 6): a relocate-willing candidate SEES on-site roles (they're no
longer hard-hidden), but genuine remote roles stay ranked above them; and a match that no longer
passes the current hard filters is swept even when its posting fell out of the recall set."""
from sqlalchemy import select

import app.application.usecases.search as crawl
from app.data.db import SessionLocal
from app.data.models import Match
from app.domain.filters import location_ok, passes_hard_filters, commute_factor
from tests.test_crawl import _make_profile_row
from tests.test_recall import _post


class _Prof:
    def __init__(self, remote_pref="remote", relocate=False, location_pref="", country="Bulgaria"):
        self.remote_pref, self.relocate = remote_pref, relocate
        self.location_pref, self.country = location_pref, country
        self.target_roles = "Backend Developer"
        self.experience = ""


_ONSITE_DE = "Berlin, Germany"


# ---- hard filter: relocate unlocks on-site ----
def test_relocate_makes_location_permissive():
    assert location_ok(_Prof(relocate=False), _ONSITE_DE) is False   # remote seeker, located role
    assert location_ok(_Prof(relocate=True), _ONSITE_DE) is True     # willing to move -> shown


def test_relocate_exempts_onsite_and_hybrid_drop():
    onsite_desc = "This is an office-based role, no remote."
    # remote seeker, NOT relocating -> the on-site posting is hard-dropped
    ok, reason = passes_hard_filters(_Prof(relocate=False), "Backend Developer", "", onsite_desc)
    assert ok is False and reason == "location"
    # same posting, willing to relocate -> it passes (surfaced, to be soft-weighted)
    assert passes_hard_filters(_Prof(relocate=True), "Backend Developer", "", onsite_desc)[0] is True


# ---- commute soft factor ----
def test_commute_downweights_onsite_for_remote_seeker():
    p = _Prof(remote_pref="remote", relocate=True)
    assert commute_factor(p, _ONSITE_DE, "", onsite=0.85) == 0.85          # concrete place -> penalty
    assert commute_factor(p, "Remote", "", onsite=0.85) == 1.0            # remote location -> none
    assert commute_factor(p, "", "Fully remote team", onsite=0.85) == 1.0  # fully-remote text -> none
    assert commute_factor(p, "", "Great perks and team", onsite=0.85) == 1.0  # unknown loc -> neutral


def test_commute_hybrid_from_description():
    # dev.bg carries no location field — the hybrid cue lives only in the text
    p = _Prof(remote_pref="remote", relocate=True)
    assert commute_factor(p, "", "Flexible hybrid work in Plovdiv", onsite=0.85) == 0.85


def test_commute_neutral_when_not_remote_seeker():
    assert commute_factor(_Prof(remote_pref="any"), _ONSITE_DE, "", onsite=0.85) == 1.0
    assert commute_factor(_Prof(remote_pref="onsite"), _ONSITE_DE, "", onsite=0.85) == 1.0


# ---- zombie sweep (integration) ----
def test_zombie_match_swept_when_posting_fails_current_filter():
    with SessionLocal() as db:
        # an on-site role unrelated to the profile -> it is NOT in the recall set
        zp = _post(db, "Data Entry Clerk", "zomb1", company="Foo")
        zp.location = _ONSITE_DE
        db.commit()
        p = _make_profile_row(db, target_roles="Backend", skills="Python")
        p.remote_pref, p.relocate = "remote", False
        db.add(Match(profile_id=p.id, posting_id=zp.id, score=90, covered=[], missing=[]))
        db.commit()
        crawl.search_db(db, p)
        # the on-site posting fails the remote hard filter now -> its stale match is gone
        assert db.execute(select(Match).where(Match.posting_id == zp.id)).first() is None


def test_valid_out_of_recall_match_is_kept():
    with SessionLocal() as db:
        zp = _post(db, "Data Entry Clerk", "zomb2", company="Foo")
        zp.location = "Remote"                       # still passes the remote filter
        db.commit()
        p = _make_profile_row(db, target_roles="Backend", skills="Python")
        p.remote_pref, p.relocate = "remote", False
        db.add(Match(profile_id=p.id, posting_id=zp.id, score=90, covered=[], missing=[]))
        db.commit()
        crawl.search_db(db, p)
        # out of recall but still valid -> the match survives (recall gap is not a reason to drop)
        assert db.execute(select(Match).where(Match.posting_id == zp.id)).first() is not None
