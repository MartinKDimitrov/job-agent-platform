"""Language signal: detect a posting's language and down-weight ones the user can't read."""
from app.domain.language import detect_language, user_language_codes, language_factor

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
