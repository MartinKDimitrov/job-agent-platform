"""EU expansion wave 1: candidate list sanity + the automated identity gate
(the phantom-board lesson: a guessed slug must prove WHO it belongs to)."""
import re

import app.data.ats_detect as ats
from app.data.companies_eu import EU_COMPANIES, EU_COUNTRY_CODES


# ---- candidate list sanity ----
def test_eu_list_shape():
    names = [c["name"] for c in EU_COMPANIES]
    assert len(names) == len(set(names)), "duplicate company names"
    for c in EU_COMPANIES:
        assert re.fullmatch(r"[A-Z]{2}", c["country"]), c
        assert c["website"].startswith("https://"), c
        assert c["industry"], c
    assert "BG" not in EU_COUNTRY_CODES          # BG lives in companies_bg.py
    assert len(EU_COMPANIES) >= 120


def test_no_overlap_with_bg_registry():
    from app.data.companies_bg import BG_COMPANY_NAMES
    assert not set(c["name"] for c in EU_COMPANIES) & set(BG_COMPANY_NAMES)


# ---- names_match ----
def test_names_match_exact_and_legal_suffixes():
    assert ats.names_match("UiPath", "UiPath Inc.")
    assert ats.names_match("Trade Republic", "Trade Republic Bank GmbH")


def test_names_match_rejects_brand_only_containment():
    # the KBC lesson: a 3-letter brand inside a stranger's longer name must not pass
    assert not ats.names_match("KBC", "KBC Bank München")
    assert not ats.names_match("Prima Assicurazioni", "Prima Power")


def test_names_match_rejects_unrelated():
    assert not ats.names_match("Adyen", "Randstad")
    assert not ats.names_match("Mollie", "")


# ---- detect_verified policy ----
def test_guessed_slug_needs_matching_board_name(monkeypatch):
    monkeypatch.setattr(ats, "probe_slug", lambda a, s: True)          # every board "exists"
    monkeypatch.setattr(ats, "board_display_name", lambda a, s: "Somebody Else GmbH")
    assert ats.detect_verified("Adyen") is None                        # identity mismatch

    monkeypatch.setattr(ats, "board_display_name", lambda a, s: "Adyen N.V.")
    found = ats.detect_verified("Adyen")
    assert found is not None and found[1] == "adyen"


def test_guessing_skips_atses_without_name_api(monkeypatch):
    probed = []
    monkeypatch.setattr(ats, "probe_slug", lambda a, s: probed.append(a) or False)
    ats.detect_verified("Adyen")
    # lever/ashby/personio expose no organization name -> never probed via guesses
    assert set(probed) & {"lever", "ashby", "personio"} == set()
    assert probed                                                       # name-APIs were tried


def test_careers_page_board_is_authoritative(monkeypatch):
    # the company's own site links the board — no name check needed (that WAS the identity)
    monkeypatch.setattr(ats, "scan_careers_page", lambda url: ("lever", "adyen"))
    monkeypatch.setattr(ats, "probe_slug", lambda a, s: True)
    assert ats.detect_verified("Adyen", careers_url="https://www.adyen.com/careers") \
        == ("lever", "adyen")


def test_dead_careers_board_falls_back_to_verified_guessing(monkeypatch):
    monkeypatch.setattr(ats, "scan_careers_page", lambda url: ("greenhouse", "adyen"))
    calls = {"n": 0}

    def probe(a, s):
        calls["n"] += 1
        return calls["n"] > 1            # careers-derived probe dies, later guesses live
    monkeypatch.setattr(ats, "probe_slug", probe)
    monkeypatch.setattr(ats, "board_display_name", lambda a, s: "Adyen")
    assert ats.detect_verified("Adyen", careers_url="https://x") is not None
