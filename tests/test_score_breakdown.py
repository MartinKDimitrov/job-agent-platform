"""Score breakdown: the soft multipliers that moved a match's score, for the 'why' UI."""
from datetime import datetime

from app.application.usecases.search import soft_factors
from app.presentation.routers.profiles import _score_breakdown

_DE = ("Wir suchen einen erfahrenen Softwareentwickler für unser Team, der mit unserer Plattform "
       "arbeitet und zuverlässige Dienste für das Unternehmen und die Kunden entwickelt.")


class _Post:
    def __init__(self, title, description="", location="", posted_at=None):
        self.title, self.description, self.location = title, description, location
        self.posted_at = posted_at or datetime.utcnow()
        self.first_seen = self.posted_at
        self.salary_min = self.salary_max = self.salary_currency = self.salary_period = None


class _Prof:
    def __init__(self, languages="", target_roles="", salary_expectation=""):
        self.languages, self.target_roles = languages, target_roles
        self.salary_expectation = salary_expectation
        self.remote_pref, self.relocate = "any", False    # neutral: no location penalty
        self.location_pref, self.country = "", "Bulgaria"


def test_soft_factors_named_values():
    post = _Post("Junior Android Engineer", description=_DE, location="Berlin, Germany")
    prof = _Prof(languages="English C1", target_roles="Senior Android")
    f = soft_factors(prof, post)
    assert f["language"] == 0.5            # German text, English-only reader -> can't read it
    assert f["seniority"] == 0.75          # junior role for a senior profile -> over-qualified
    assert f["freshness"] == 1.0 and f["salary"] == 1.0    # fresh, no salary signal


def test_breakdown_renders_the_penalties():
    post = _Post("Junior Android Engineer", description=_DE, location="Berlin, Germany")
    prof = _Prof(languages="English C1", target_roles="Senior Android")
    html = _score_breakdown(prof, post, "en")
    assert "language you can" in html and "×0.50" in html      # apostrophe is HTML-escaped
    assert "below your level" in html and "×0.75" in html


def test_breakdown_empty_for_a_clean_match():
    post = _Post("Senior Android Engineer", description="We build great mobile apps with Kotlin.",
                 location="Remote")
    prof = _Prof(languages="English, German", target_roles="Senior Android")
    assert _score_breakdown(prof, post, "en") == ""    # nothing moved the score
