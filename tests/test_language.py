"""Language signal: detect a posting's language and down-weight ones the user can't read."""
from app.domain.language import (detect_language, user_language_codes, language_factor,
                                 country_language, required_languages)

_EN = ("We are looking for a backend engineer to join our team. You will work with our "
       "platform and build reliable services for the company and its customers every day.")
_DE = ("Wir suchen einen Softwareentwickler für unser Team. Sie werden mit unserer Plattform "
       "arbeiten und zuverlässige Dienste für das Unternehmen und die Kunden entwickeln.")
_FR = ("Nous recherchons un ingénieur backend pour rejoindre notre équipe. Vous travaillerez "
       "avec notre plateforme et construirez des services fiables pour les clients.")
_BG = ("Търсим backend инженер за нашия екип. Ще работите с нашата платформа и ще изграждате "
       "надеждни услуги за компанията и нейните клиенти всеки ден.")


def test_detect_language():
    assert detect_language(_EN) == "en"
    assert detect_language(_DE) == "de"
    assert detect_language(_FR) == "fr"
    assert detect_language(_BG) == "bg"
    assert detect_language("short text") is None          # too short to judge
    assert detect_language("") is None


def test_user_language_codes():
    assert user_language_codes("English C1, German B2") == {"en", "de"}
    assert user_language_codes("Български (роден), Английски B2") == {"bg", "en"}
    assert user_language_codes("") == set()


def test_language_factor_penalizes_unreadable_postings():
    langs = "English C1, German B2"
    assert language_factor(langs, _EN) == 1.0            # English -> always readable
    assert language_factor(langs, _DE) == 1.0            # user reads German
    assert language_factor(langs, _FR, unreadable=0.5) == 0.5   # French -> can't read
    assert language_factor(langs, _BG, unreadable=0.5) == 0.5   # Bulgarian -> can't read


def test_language_factor_no_signal_without_data():
    assert language_factor("", _FR) == 1.0               # no user-language data -> no penalty
    assert language_factor("English", "short") == 1.0    # undetectable posting -> no penalty


def test_bulgarian_speaker_reads_bulgarian_and_english():
    langs = "Bulgarian native, English B1"
    assert language_factor(langs, _BG) == 1.0
    assert language_factor(langs, _EN) == 1.0
    assert language_factor(langs, _DE, unreadable=0.4) == 0.4   # no German


# ---- signal (2): country language ----
def test_country_language():
    assert country_language("Berlin, Germany") == "de"
    assert country_language("Milano, Italia") == "it"
    assert country_language("Sofia, България") == "bg"
    assert country_language("London, UK") == "en"
    assert country_language("Remote") == "en"
    assert country_language("Atlantis") is None


def test_signal2_mild_penalty_for_english_posting_in_foreign_country():
    langs = "English C1"                                  # speaks only English
    # English posting located in Germany -> readable, but everyday language is German -> mild
    assert language_factor(langs, _EN, "Berlin, Germany", foreign_country=0.9) == 0.9
    # same posting in London -> English country -> no penalty
    assert language_factor(langs, _EN, "London, UK") == 1.0
    # a German speaker is fine in Germany
    assert language_factor("English, German", _EN, "Berlin, Germany") == 1.0


# ---- signal (3): explicit language requirement ----
def test_required_languages():
    assert required_languages("Fließende Deutschkenntnisse erforderlich") == {"de"}
    assert required_languages("Fluent German (C1) is required") == {"de"}
    assert required_languages("italiano fluente richiesto") == {"it"}
    assert required_languages("Native French speaker") == {"fr"}
    assert required_languages("We build great software with modern tools") == set()


def test_signal3_explicit_requirement_dominates():
    langs = "English C1"                                  # no German
    # posting is in English (readable) but explicitly requires fluent German -> strong penalty
    text = _EN + " Fluent German (C1) is required for this role."
    assert language_factor(langs, text, "Berlin, Germany", unreadable=0.5) == 0.5
    # a German speaker meets the requirement -> no penalty
    assert language_factor("English, German", text, "Berlin, Germany") == 1.0
