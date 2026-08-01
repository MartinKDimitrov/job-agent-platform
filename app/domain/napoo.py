"""Map a НАПОО professional direction to one of our occupation verticals, so a profile can show
the official Bulgarian competencies for its FIELD. Direction names are field-level and don't share
tokens with narrow occupation labels ('бетонджия' vs 'Строителство'), so we bucket by keyword into
the same 16 verticals `Occupation.vertical` uses. First matching rule wins (order = specificity)."""

# (vertical, substring cues in the direction name, lowercased)
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("construction", ("строителств", "архитектура", "водно строит", "транспортно строит",
                      "парково", "недвижим")),
    ("ict", ("софтуер", "данни", "компютър", "мрежи", "дигитал", "информационн", "информацион",
             "роботика", "интелигентни систем", "микропроцес", "интерфейс", "медии", "икономическа информатика")),
    ("finance", ("счетовод", "банков", "застрахов", "осигурителн", "митническо",
                 "мениджмънт и икономика", "малък и среден бизнес", "индустриалните отношения")),
    ("healthcare", ("дентал", "здравен", "парамедик", "очна оптика", "оптометрич", "балнеолог",
                    "ветеринар", "медицинска техника")),   # pharma-MANUFACTURING is crafts, not clinical
    ("personal_services", ("фризьор", "козметич", "маникюр", "педикюр", "фитнес", "арома",
                           "социални дейности")),
    ("agriculture", ("агро", "ферм", "пчелар", "лозаро", "гори", "горско", "флорист", "озелен",
                     "растителна", "кинолог", "биопроизвод")),
    ("education", ("възпитател", "медиация", "библиотек", "жестов", "посредничество")),
    ("sales", ("търгов", "продажб", "реклам", "маркетинг")),
    ("legal_culture", ("изкуства", "музикал", "танцов", "актьор", "дизайн", "фотограф", "анимация",
                       "графика", "полиграф", "реставрац", "мода", "текстил", "аксесоари",
                       "съдебна администрация", "културно наследство")),
    ("admin", ("административни", "офис дейности")),
    ("machine_ops", ("автомобилна", "железопът", "кораб", "въздухоплавател", "подемно-транспортна",
                     "пристанищна", "пътностроителна", "релсов", "автобояджийство", "мехатроника",
                     "тролейбус", "превозни средства", "летателни", "безпилотни")),
    ("legal_culture", ("аудио", "видео", "кино")),
    ("engineering", ("електро", "електрич", "енергетик", "енергийни", "машин", "автоматизац", "геолог", "геодез",
                     "хидро", "метеоролог", "маркшайдер", "сондиране", "химич", "металург", "метал",
                     "заваряване", "оптични и лазерни", "радиоактивни", "асансьор", "мерителна",
                     "лабораторен контрол", "силикат", "целулоза", "екохимич", "неорганич", "органич",
                     "измерителна", "измервателна", "отопление")),
    ("crafts", ("мебел", "обувно", "производство", "тапицир", "каменодел", "лютиер", "изкопаеми",
                "суровини", "преработка", "хляб", "мляко", "захар", "месо", "напитки", "масла",
                "храни", "зелени технологии", "екология", "устойчиво развитие", "кръгова икономика",
                "фармацевтични", "парфюмерийно")),
)


def direction_vertical(name: str) -> str:
    t = (name or "").lower()
    for vert, cues in _RULES:
        if any(c in t for c in cues):
            return vert
    return ""


import re as _re

_STOP = {"и", "на", "за", "от", "с", "в", "по", "при", "или", "към", "до", "техник", "оператор",
         "монтьор", "работник", "специалист", "младши", "старши", "главен", "помощник"}


def _roots(text: str) -> set[str]:
    """5-char stems of the meaningful words — crude Bulgarian stemming so 'заварчик' ~ 'заваряване',
    'счетоводител' ~ 'счетоводство' still overlap despite different inflections/suffixes."""
    toks = _re.findall(r"[а-яa-zё]{4,}", (text or "").lower())
    return {t[:5] for t in toks if t not in _STOP}


def best_direction(terms, vertical: str, directions) -> str:
    """The NAPOO direction (name) that best matches a specific occupation by name — many directions
    ARE named like professions (Здравен асистент, Фризьорство, Заваряване). Scored by shared word
    roots; the occupation's own vertical is a tiebreaker, NOT a filter (our ESCO vertical and the
    direction's don't always agree — a welder is 'crafts' but 'Заваряване' maps to 'engineering').
    Returns "" when nothing overlaps (caller falls back to the vertical-wide competencies)."""
    occ = set()
    for t in terms:
        occ |= _roots(t)
    if not occ:
        return ""
    best, best_key = "", (0, 0)
    for name, dvert in directions:
        score = len(occ & _roots(name))
        key = (score, 1 if dvert == vertical else 0)     # more roots wins; same-vertical breaks ties
        if score >= 1 and key > best_key:
            best, best_key = name, key
    return best
