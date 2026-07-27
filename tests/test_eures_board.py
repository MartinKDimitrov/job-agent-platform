"""EURES board — per-country tallies derived from persisted postings."""
from app.application.usecases import eures_board as eb
from app.data.db import SessionLocal
from app.data.models import Posting


def _p(loc):
    return Posting(title="t", company="c", url=f"https://europa.eu/eures/portal/jv-se/jv-details/{loc}",
                   apply_url="x", location=loc, description="d", content_hash=f"h-{loc}")


def test_status_counts_per_country_and_splits_multi():
    with SessionLocal() as db:
        db.add_all([_p("BG"), _p("BG2"), _p("RO"), _p("DE, DK"),
                    Posting(title="x", company="c", url="https://other/1", apply_url="x",
                            location="BG", description="d", content_hash="hx")])   # non-EURES url
        # fix content_hash uniqueness: BG and BG2 have different hashes; location for BG2 is "BG2"
        db.commit()
        st = eb.status(db)
    countries = dict(st["countries"])
    assert st["total"] == 4                       # only the 4 EURES-url postings
    assert countries.get("BG") == 1               # "BG2" isn't a valid 2-letter code -> dropped
    assert countries.get("RO") == 1
    assert countries.get("DE") == 1 and countries.get("DK") == 1   # multi split into both


def test_render_board_reflects_status():
    st = {"total": 250, "countries": [("BG", 120), ("RO", 80), ("EL", 50)]}
    html = eb.render_board(st)
    assert "EURES" in html and "250" in html
    assert "България" in html and "Гърция" in html   # EL -> Greece name
    assert "2<small>ДЪРЖАВИ" not in html             # 3 countries
