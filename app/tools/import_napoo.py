"""Parse the НАПОО ДОС (state educational standards, СППОО-2024) into a Bulgarian vocational-skills
overlay — a display/CV layer of the official знания/умения/компетентности each professional
direction's curriculum covers. ESCO stays the matching backbone; this is BG-only, descriptive.

Each direction is one PDF (Наредба, published in Държавен вестник) with a regular table structure:
rows tagged Знания / Умения / Компетентности, items bullet-separated. We extract atomic statements.

    python -m app.tools.import_napoo            # download + parse every direction, store
    python -m app.tools.import_napoo <name>     # just the directions whose name contains <name>
"""
import io
import re
import sys

import httpx
import pdfplumber
from sqlalchemy import select

from ..data.db import SessionLocal, engine, Base
from ..data.models import NapooDirection

_SECT = {"Знания": "knowledge", "Умения": "skills", "Компетентности": "competencies"}
_NOISE = re.compile(r"източник|сиела|правно-информационни|държавен вестник", re.I)
# A ДОС ends with the profession-SPECIFIC section, introduced by a header carrying "по професията"
# (distinct from the intro's "общата, отрасловата и специфичната ... подготовка"). Everything from
# that header on is specific; we emit it FIRST so a welder's list leads with МИГ/МАГ заваряване, not
# the shared technical-drawing foundation. Umения before it (обща+отраслова) come after, with the
# generic health-and-safety/entrepreneurship noise dropped.
_SPECIFIC_MARK = re.compile(r"специфична\s+професионална\s+подготовка\s+по\s+професията", re.I)
_GENERIC = re.compile(
    r"безопасн|аварий|първа помощ|злополук|предприемач|икономическ|пазар|бизнес план|хигиенн|"
    r"околната среда|отпадъц|комуникац|нормативни акт|устойчиви практики|въглеродния", re.I)
# ДОС PDFs use different bullet glyphs for list items ( in some, ∙ in others).
_BULLETS = re.compile("["+chr(0xf0b7)+chr(0x2219)+chr(0xb7)+chr(0x2022)+"]")

# (direction name, ДОС PDF url) — the full СППОО-2024 archive (navet.government.bg/bg/dos-lp-2024-sg)
_M = "https://www.navet.government.bg/bg/media/"
DIRECTIONS: list[tuple[str, str]] = [
    ("Помощник-възпитател", _M + "narerba-64-04.11.2025-dos-pomoshtnik-vazpitatel.pdf"),
    ("Образователна медиация", _M + "narerba-63-04.11.2025-dos-obrazovatelna-mediatziq.pdf"),
    ("Графичен дизайн", _M + "naredba-25-ot-9.10.2025-dos-grafichen-dizajn-dv-86-16.10.2025.pdf"),
    ("Компютърна графика", _M + "naredba-22-ot-9.10.2025-dos-kompyutarna-grafika-dv-86-16.10.2025-1.pdf"),
    ("Рекламна графика", _M + "dos-reklamna-grafika-dv.pdf"),
    ("Фотография", _M + "naredba-21-ot-9.10.2025-dos-fotografiya-dv86-16.10.2025-dvv.pdf"),
    ("Анимация", _M + "dos-animacziya-dv.pdf"),
    ("Полиграфия", _M + "naredba-27-ot-9.10.2025-dos-poligrafiya-dv-86-16.10.2025.pdf"),
    ("Моден дизайн", _M + "naredba-24-ot-9.10.2025-dos-moden-dizajn-dv-86-16.10.2025.pdf"),
    ("Интериорен и екстериорен дизайн", _M + "naredba-dos-interioren-i-eksterioren-dizajn.pdf"),
    ("Промишлен дизайн", _M + "naredba-23-ot-9.10.2025-dos-promishlen-dizajn-dv-86-16.10.2025.pdf"),
    ("Силикатен дизайн", _M + "dos-silikaten-dizajn-dv.pdf"),
    ("Изящни изкуства", _M + "dos-izyasthni-izkustva-dv.pdf"),
    ("Приложни изкуства", _M + "dos-prilozhni-izkustva-dv.pdf"),
    ("Лютиерство", _M + "naredba-dos-lyutierstvo.pdf"),
    ("Каменоделство", _M + "dos-kamenodelstvo-dv.pdf"),
    ("Музикално изкуство", _M + "dos-muzikalno-izkustvo-dv.pdf"),
    ("Танцово изкуство", _M + "dos-tanczovo-izkustvo-dv.pdf"),
    ("Актьорство", _M + "dos-aktyorstvo-dv.pdf"),
    ("Библиотекознание", _M + "naredba-37-ot17.10.2025-dos-032201-bibliotekoznanie-dv-89-24.10.2025.pdf"),
    ("Оперативно счетоводство", _M + "naredba-42-22.10.2025-dos-operativno-schetovodstvo-dv-90-28.10.2025.pdf"),
    ("Митническо обслужване", _M + "naredba-43-22.102025-dos-mitnichesko-obslujvane-dv-90-28.10.2025.pdf"),
    ("Банково, застрахователно и осигурително дело", _M + "naredba-41-22.10.2025-dos-bankovo-zastrahovatelno-i-osig.-delo-dv-90-28.10.2025.pdf"),
    ("Мениджмънт и икономика", _M + "naredba-44-22.10.2025-dos-menidjmant-i-ikonomika-dv-90-28.10.2025.pdf"),
    ("Малък и среден бизнес", _M + "dos-041302-malak-i-sreden-biznes-1.pdf"),
    ("Административни и офис дейности", _M + "naredba-50-ot-22.10.2025-dos-041501-administrativni-i-ofis-deinosti-dv-92-31.10.2025.pdf"),
    ("Съдебна администрация", _M + "dos-041502-sadebna-administracziya.pdf"),
    ("Търговия и продажби", _M + "dos-041601-turgovia-i-prodazhbi.pdf"),
    ("Електронна търговия, маркетинг и реклама", _M + "dos-041602-elektronna-targoviya-marketing-i-reklama-1.pdf"),
    ("Икономическа информатика", _M + "dos-041603-ikonomicheska-informatika-1.pdf"),
    ("Управление на индустриалните отношения", _M + "dos-041701-upravlenie-na-industrialnite-otnoshenia-1.pdf"),
    ("Геология и геофизика", _M + "naredba-34-ot-14.10.2025-dos-geologiya-i-geofizika-dv-88-21.10.2025.pdf"),
    ("Хидрология, хидрогеология и метеорология", _M + "naredba-35-ot-14.10.2025-dos-hidrologiya-hidrogeologiya-i-meteorologiya-dv-88-21.10.2025.pdf"),
    ("Геодезия", _M + "naredba-36-ot-14.10.2025-dos-geodeziya-dv-88-21.10.2025.pdf"),
    ("Информационна инфраструктура", _M + "naredba-69-ot-21.11.2025-dos-informaczionna-infrastruktura-dv-101-27.11.2025.pdf"),
    ("Информационни системи", _M + "naredba-70-ot-21.11.-2025-dos-informaczionni-sistemi-dv-101-27.11.2025.pdf"),
    ("Интегриране на дигитални технологии", _M + "naredba-71-ot-21.11.2025-dos-integrirane-na-digitalni-tehnologii-dv-101-27.11.2025.pdf"),
    ("Потребителски интерфейс и ползваемост на софтуер", _M + "naredba-72-ot-21.11.2025-dos-potrebitelski-interfejs-i-polzvaemost-na-softuer-dv-101-27.11.2025.pdf"),
    ("Дизайн на дигитални и печатни медии", _M + "naredba-73-ot-21.11.2025-dos-dizajn-na-digitalni-i-pechatni-medii-dv-101-27.11.2025.pdf"),
    ("Интелигентни системи", _M + "naredba-75-ot-21.11.2025-dod-inteligentni-sistemi-dv-101-27.11.2025.pdf"),
    ("Анализ на данни", _M + "naredba-74-ot-21.11.2025-dos-analiz-na-danni-dv-101-27.11.2025.pdf"),
    ("Разработка на софтуер", _M + "naredba-81-ot-28.11.2025-dos-razrabotka-na-softuer-dv-104-05.12.2025.pdf"),
    ("Осигуряване на качество на софтуер", _M + "naredba-76-ot-21.11.2025-dos-osiguryavane-na-kachestvo-na-softuer-dv-102-28.11.2025.pdf"),
    ("Неорганични и електрохимични процеси", _M + "naredba-97-ot-5.12.2025-dos-neorganichni-i-elektrohimichni-proczesi-dv-107-12.12.2025.pdf"),
    ("Органични химични технологии", _M + "naredba-96-ot-5.12.2025-dos-organichni-himichni-tehnologii-dv-107-12.12.2025.pdf"),
    ("Силикатни технологии", _M + "naredba-95-ot-512.2025-dos-silikatni-tehnologii-dv-107-12.12.2025.pdf"),
    ("Технологии в биопроизводствата", _M + "naredba-109-ot-9.12.2025-dos-tehnologii-v-bioproizvodstvata-dv-110-ot-17.12.2025.pdf"),
    ("Лабораторен контрол в химични, хранителни и биотехнологични производства", _M + "naredba-110-ot-9.12.-2025-dos-laboratoren-kontrol-v-himichni-hranitelni-i-biotehnologichni-proizvodstva-dv-110-ot-17.12.2025.pdf"),
    ("Технологии на фармацевтични и парфюмерийно-козметични продукти", _M + "naredba-111-ot-9.12.2025-dos-tehnologii-na-farmaczevtichni-i-parfyumerijno-kozmetichni-produkti-dv-110-ot-17.12.2025.pdf"),
    ("Технологии на целулоза и хартия", _M + "naredba-98-ot-5.12.2025-dos-tehnologii-na-czeluloza-i-hartiya-dv-107-12.12.2025.pdf"),
    ("Екохимични, биологични продукти и битова химия", _M + "naredba-99-ot-5.12.2025-dos-ekohimichni-biologichni-produkti-i-bitova-himiya-dv-107-12.12.2025.pdf"),
    ("Екология и опазване на околната среда", _M + "naredba-91-ot-3.12.2025-do-ekologiya-i-opazvane-na-okolnata-sreda-dv-106-9.12.2025.pdf"),
    ("Зелени технологии, кръгова икономика и устойчиво развитие", _M + "naredba-93-ot-3.12.2025-dos-zeleni-tehnologii-kragova-ikonomika-i-ustojchivo-razvitie-dv-107-12.12.2025.pdf"),
    ("Електроенергетика", _M + "naredba-87-ot-3.12.2025-dos-elektroenergetika-dv-105-06.12.2025.pdf"),
    ("Електрически инсталации", _M + "naredba-82-ot-3.12.2025-dos-elektricheski-instalaczii-dv-105-06.12.2025.pdf"),
    ("Електроснабдяване и електрообзавеждане", _M + "naredba-90-ot-3.12.2025-dos-elektrosnabdyavane-i-elektroobzavezhdane-dv-106-9.12.2025.pdf"),
    ("Възобновяеми енергийни източници", _M + "naredba-83-ot-3.12.2025-g.-dos-vazobnovyaemi-energijni-iztochniczi-dv-105-06.12.2025.pdf"),
    ("Корабни електрически системи", _M + "naredba-92-ot-3.12.2025-dos-korabni-elektricheski-sistemi-dv-106-9.12.2025.pdf"),
    ("Асансьорна техника и съоръжения", _M + "naredba-89-ot-3.12.2025-dos-asansyorna-tehnika-i-saorazheniya-dv-106-9.12.2025.pdf"),
    ("Топлоенергетика", _M + "naredba-86-ot-3.12.2025-dos-toploenergetika-dv-105-06.12.2025.pdf"),
    ("Ядрена енергетика", _M + "naredba-88-ot-3.12.2025-dos-yadrena-energetika-dv-105-06.12.2025.pdf"),
    ("Управление на радиоактивни отпадъци", _M + "naredba-84-ot-3.12.2025-dos-upravlenie-na-radioaktivni-otpadaczi-dv-105-06.12.2025.pdf"),
    ("Отопление, вентилация, климатизация и газова техника", _M + "naredba-94-ot-3.12.2025-dos-otoplenie-ventilacziya-klimatizacziya-i-gazova-tehnika-dv-107.12.2025.pdf"),
    ("Автоматизация и управляваща техника", _M + "naredba-13-ot-6.10.2025-dos-avtomatizacziya-i-upravlyavastha-tehnika-dv-85-14.10.2025.pdf"),
    ("Роботика", _M + "naredba-15-ot-6.10.2025-dos-robotika-dv-85-14.10.2025.pdf"),
    ("Безпилотни летателни апарати", _M + "dos-071403.pdf"),
    ("Компютърни системи и технологии", _M + "naredba-16-ot-6.10.2025-dos-kompyutarni-sistemi-i-tehnologii-dv-85-14.10.2025.pdf"),
    ("Комуникационни и компютърни мрежи", _M + "naredba-17-ot-6.10.2025-dos-komunikaczionni-i-kompyutarni-mrezhi-dv-85-14.10.2025.pdf"),
    ("Микропроцесорни системи", _M + "naredba-18-ot-6.10.2025-dos-mikroproczesorni-sistemi-dv-86-16.10.2025.pdf"),
    ("Електронна техника и технологии", _M + "naredba-14-ot-6.10.2025-dos-elektronna-tehnika-i-tehnologii-dv-85-14.10.2025.pdf"),
    ("Кино-, аудио- и видеосистеми", _M + "dos071408.pdf"),
    ("Автоматизирани системи и технологии в машиностроенето", _M + "naredba-104-ot-9.12.2025-dos-avtomatizirani-sistemi-i-tehnologii-v-mashinostroeneto-dv-108-13.12.2025.pdf"),
    ("Индустриална мехатроника", _M + "naredba-103-ot-9.12.2025-dos-industrialna-mehatronika-dv-108-13.12.2025.pdf"),
    ("Машини, съоръжения и системи в индустрията", _M + "naredba-106-ot-9.12.2025-dos-mashini-saorazheniya-i-sistemi-v-industriyata-dv-110-17.12.2025.pdf"),
    ("Зелени технологии в черната металургия", _M + "naredba-121-ot-16-12-2025-zeleni-tehnologii-v-chernata-metalurgiya.pdf"),
    ("Металургия на цветните и благородните метали", _M + "naredba-107-ot-9.12.2025-dos-metalurgiya-na-czvetnite-i-blagorodnite-metali-dv-110-ot-17.12.2025.pdf"),
    ("Технологии на метални продукти и изделия", _M + "naredba-122-ot-16-dekemvri-2025-tehnologii-na-metalni-produkti-i-izdeliya.pdf"),
    ("Технологии и системи за заваряване", _M + "naredba-123-ot-16-dekemvri-2025-tehnologii-i-sistemi-za-zavaryavane.pdf"),
    ("Оптични и лазерни системи", _M + "naredba-101-ot-9.12.2025-dos-optichni-i-lazerni-sistemi-dv-108-13.12.2025.pdf"),
    ("Медицинска техника", _M + "naredba-100-ot-9.12.2025-dos-mediczinska-tehnika-dv-108-13.12.2025.pdf"),
    ("Индустриален дизайн и технологии", _M + "naredba-102-ot-9.12.2025-dos-industrialen-dizajn-i-tehnologii-dv-108-13.12.2025.pdf"),
    ("Информационно-измервателна и офис техника", _M + "naredba-No-105-ot-9.12.2025-dos-informaczionno-izmervatelna-i-ofis-tehnika-dv-108-13.12.2025.pdf"),
    ("Автомобилна техника и мехатроника", _M + "naredba-118-ot-16.12.2025-dos-avtomobilna-tehnika-i-mehatronika-dv-2-08.01.2026.pdf"),
    ("Хибридни и електрически пътни превозни средства", _M + "naredba-114-ot-12.12.2025-dos-hibridni-i-elektricheski-patni-prevozni-sredstva-dv-112-ot-19.12.2025.pdf"),
    ("Електрообзавеждане на тролейбуси и електрически автобуси", _M + "naredba-115-ot-12.12.2025-dos-elektroobzavezhdane-na-trolejbusi-i-elektricheski-avtobusi-dv-112-ot-19.12.2025.pdf"),
    ("Пътностроителна техника", _M + "naredba-119-ot-16.12.2025-dos-patnostroitelna-tehnika-dv-2-08.01.2026.pdf"),
    ("Подемно-транспортна техника, монтирана на пътни транспортни средства", _M + "naredba-116-ot-16.12.2025-dos-podemno-transportna-tehnika-montirana-na-patni-transportni-sredstva-dv-114-24.12.2025.pdf"),
    ("Подемно-транспортна техника с електрозадвижване", _M + "naredba-120-ot-16.122025-dos-podemno-transportna-tehnika-s-elektrozadvizhvane-dv-2-08.01.2026.pdf"),
    ("Пристанищна механизация", _M + "naredba-117-ot-16.12.2025-dos-pristanisthna-mehanizacziya-dv-2-08.01.2026.pdf"),
    ("Автобояджийство", _M + "naredba-dos-avtoboyadzhijstvo-1-spk.pdf"),
    ("Железопътна техника – локомотиви и вагони", _M + "naredba-128-ot-29.12.2025-dos-zhelezopatna-tehnika-lokomotivi-i-vagoni-dv-5-15.01.2026.pdf"),
    ("Железопътна механизация", _M + "naredba-2-ot-05.01.2026-dos-zhelezopatna-mehanizacziya-dv-5-15.01.2026-izm.-dv-33-03.04.2026.pdf"),
    ("Електрообзавеждане на релсов транспорт", _M + "naredba-1-ot-5.01.2026-dos-elektroobzavezhdane-na-relsov-transport-dv-5-15.01.2026-izm.-dv-33-3.04.2026.pdf"),
    ("Корабни машини и механизми", _M + "naredba-31-ot-19.01.2026-dos-korabni-mashini-i-mehanizmi-dv-13-03.02.2026.pdf"),
    ("Корабостроене и кораборемонт", _M + "naredba-18-ot-09.01.2026-dos-korabostroene-i-koraboremont-dv-9-23.01.2026.pdf"),
    ("Производство на хляб, хлебни и сладкарски изделия", _M + "naredba-9-ot-5.01.206-dos-proizvodstvo-na-hlyab-hlebni-i-sladkarski-izdeliya-dv-6-16.01.2026-izm-dv-33-03.04.2026.pdf"),
    ("Производство на мляко и млечни продукти", _M + "naredba-7-ot-5.01.2026-dos-proizvodstvo-na-mlyako-i-mlechni-produkti-dv-6-16.01.2026-izm-dv-33-03.04.2026.pdf"),
    ("Производство на захар и захарни изделия", _M + "naredba-19-ot-09.01.2026-dos-proizvodstvo-na-zahar-i-zaharni-izdeliya-dv-9-23.01.2026.pdf"),
    ("Преработка на плодове и зеленчуци", _M + "naredba-8-ot-5.01.2026-dos-prerabotka-na-plodove-i-zelenchuczi-dv-6-16.01.2026-izm-dv-33-03.04.2026.pdf"),
    ("Производство на безалкохолни и алкохолни напитки", _M + "naredba-5-ot-05.01.2026-dos-proizvodstvo-na-bezalkoholni-i-alkoholni-napitki-dv-5-15.01.2026.pdf"),
    ("Производство на растителни масла и маслопродукти", _M + "naredba-4-ot-05.01.2026-dos-proizvodstvo-na-rastitelni-masla-i-masloprodukti-dv-5-15.01.2026.pdf"),
    ("Контрол на качеството и безопасност на храните", _M + "naredba-3-ot-05.01.2026-dos-kontrol-na-kachestvoto-i-bezopasnost-na-hranite-dv-5-15.01.2026.pdf"),
    ("Дигитално проектиране на мебели и интериор", _M + "dos-072201-digitalno-proektirane-na-mebeli-i-interior-1.pdf"),
    ("Мебелно производство и реставрация", _M + "narerba-59-04.11.2025-dos-mebelno-proizvodstvo-i-restavracziq.pdf"),
    ("Проектиране и производство на тапицирани мебели", _M + "narerba-60-04.11.2025-dos-proektirane-i-proizvodstvo-na-tapitzirani-mebeli.pdf"),
    ("Производство на строителни изделия от дървесина, врати и прозорци", _M + "dos-072204-proizvodstvo-na-stroitelni-izdelia-ot-darvesina-vrati-i-prozorci.pdf"),
    ("Производство на биокомпозитни материали", _M + "dos-072205-proizvodstvo-na-biokompozitni-materiali.pdf"),
    ("Устойчива мода", _M + "naredba-29-ustojchiva-moda-072301.pdf"),
    ("Текстилни технологии", _M + "naredba-33-ot-10.10.2025-dos-tekstilni-tehnologii-dv-88-21.10.2025.pdf"),
    ("Обувно производство", _M + "naredba-31-ot-10.10.2025-dos-obuvno-proizvodstvo-dv-87-17.10.2025.pdf"),
    ("Дигитален дизайн на текстил", _M + "naredba-32-ot-10.10.2025-dos-digitalen-dizajn-na-tekstil-dv-87-17.10.2025.pdf"),
    ("Производство на модни аксесоари", _M + "naredba-30-ot-10.10.2025-dos-proizvodstvo-na-modni-aksesoari-dv-87-17.10.2025.pdf"),
    ("Разработване на полезни изкопаеми", _M + "naredba-12-ot-6.10.2025-dos-razrabotvane-na-polezni-izkopaemi-dv-85-14.10.2025.pdf"),
    ("Обогатяване и рециклиране на минерални суровини", _M + "dos-072402.pdf"),
    ("Маркшайдерство", _M + "naredba-9-ot-6.10.2025-dos-markshajderstvo-dv-84-10.10.2025.pdf"),
    ("Сондиране", _M + "naredba-11-ot-6.10.2025-dos-sondirane-dv-84-10.10.2025.pdf"),
    ("Реставрация на недвижимо културно наследство", _M + "naredba-5-ot-2.10.2025-dos-restavracziya-na-nedvizhimo-kulturno-nasledstvo-dv-82-7.10.2025.pdf"),
    ("Строителство и архитектура", _M + "naredba-8-ot-2.10.2025-g.-dos-stroitelstvo-i-arhitektura-dv-84-10.10.2025.pdf"),
    ("Водно строителство", _M + "naredba-6-ot-2.10.2025-dos-vodno-stroitelstvo-dv-82-7.10.2025.pdf"),
    ("Транспортно строителство", _M + "naredba-4-ot-2.10-2025-g.-dos-transportno-stroitelstvo-dv-82-7.10.2025.pdf"),
    ("Парково строителство", _M + "naredba-7-ot-2.10.2025-dos-parkovo-stroitelstvo-dv-84-10.10.2025.pdf"),
    ("Експлоатация и сделки с недвижими имоти", _M + "naredba-28-ot-9.10.2025-dos-eksploatacziya-i-sdelki-s-nedvizhimi-imoti-dv-87-17.10.2025.pdf"),
    ("Фермерство", _M + "naredba-32-ot-20.01.2026-dos-fermerstvo-dv-13-03.02.2026.pdf"),
    ("Кинология", _M + "dos-kinologiya-utvarden-dv.pdf"),
    ("Агроекология и растителна защита", _M + "naredba-20-ot-9.01.2026-dos-agroekologiya-i-rastitelna-zasthita-dv-9-23.01.2026.pdf"),
    ("Флористика и озеленяване", _M + "naredba-21-ot-09.01.2026-dos-floristika-i-ozelenyavane-dv-9-23.01.2026.pdf"),
    ("Пчеларство", _M + "naredba-24-ot-16.01.2026-dos-pchelarstvo-dv-10-27.01.2026.pdf"),
    ("Лозаро-винарство", _M + "naredba-25-ot-16.01.2026-dos-lozaro-vinarstvo-dv-10-27.01.2026.pdf"),
    ("Стопанисване на горите", _M + "naredba-79-ot-27.11.2025-g.-dos-stopanisvane-na-gorite-dv-103-02.12.2025.pdf"),
    ("Механизация на горското стопанство", _M + "naredba-80-ot-27.11.2025-dos-mehanizacziya-na-gorskoto-stopanstvo-dv-103-2.12.2025.pdf"),
    ("Ветеринарен техник", _M + "naredba-67-ot-14.11.2025-dos-veterinaren-tehnik-dv-99-21.11.2025.pdf"),
    ("Ветеринарен лаборант", _M + "naredba-68-ot-14.11.2025-dos-veterinaren-laborant-dv-99-21.11.2025-1.pdf"),
    ("Асистиране в денталната медицина", _M + "dos-091101-asistirane-v-dentalnata-medicina.pdf"),
    ("Здравен асистент", _M + "naredba-dos-zdraven-asistent.pdf"),
    ("Парамедик", _M + "dos-paramedik-naredba.pdf"),
    ("Техник по очна оптика", _M + "dos-091401-tehnik-po-ochna-optika-1.pdf"),
    ("Оптометрична техника и рефракциониране", _M + "dos-091402-optometrichna-tehnika-i-refrakcionirane-.pdf"),
    ("Балнеологични и възстановителни процедури", _M + "dos-091501-balneologichni-i-vazstanovitelni-proceduri.pdf"),
    ("Социални дейности", _M + "naredba-65-04.11.2025-dos-sotzialni-deinosti.pdf"),
    ("Преводач от и на български жестов език", _M + "narerba-61-04.11.2025-dos-prevodach-na-jestov-ezik.pdf"),
    ("Трудово посредничество", _M + "narerba-62-04.11.2025-dos-trudovo-posrednichestvo.pdf"),
    ("Фризьорство", _M + "naredba-112-ot-10.12.2025-dos-frizyorstvo-dv-111-ot-18.12.2025.pdf"),
    ("Козметични услуги", _M + "naredba-126-ot-22.12.2025-dos-kozmetichni-uslugi-dv-4-13.01.2026.pdf"),
    ("Маникюр, педикюр и ноктопластика", _M + "naredba-85-ot-3.12-2025-dos-manikyur-pedikyur-i-noktoplastika-dv-105-06.12.2025.pdf"),
    ("Фитнес и здраве", _M + "naredba-dos-fitnes-i-zdrave.pdf"),
]


def _items(cell: str) -> list[str]:
    out = []
    for part in _BULLETS.split(cell or ""):
        p = re.sub(r"\s+", " ", part.replace("\n", " ")).strip(" •-–\t.")
        if len(p) >= 6 and not _NOISE.search(p):
            out.append(p)
    return out


def parse_pdf(src) -> dict:
    """src = path or bytes. Returns {skills, knowledge, competencies} — the profession-SPECIFIC
    section first (everything from the 'специфична ... по професията' header on), then the preceding
    обща+отраслова statements with the generic (safety/entrepreneurship/…) noise dropped."""
    spec = {"skills": [], "knowledge": [], "competencies": []}
    pre = {"skills": [], "knowledge": [], "competencies": []}
    with pdfplumber.open(src) as pdf:
        pages = pdf.pages
        # the header appears twice — once in the structure description, once right before the specific
        # tables — so the SECTION starts at the LAST occurrence, not the first.
        marks = [i for i, p in enumerate(pages) if _SPECIFIC_MARK.search(p.extract_text() or "")]
        spec_start = marks[-1] if marks else len(pages)
        for i, page in enumerate(pages):
            bucket = spec if i >= spec_start else pre
            for table in page.extract_tables() or []:
                for row in table:
                    if row and len(row) >= 2 and row[0] and (key := _SECT.get(row[0].strip())):
                        bucket[key] += _items(row[1] or "")

    def uniq(xs):
        seen, r = set(), []
        for x in xs:
            if x.lower() not in seen:
                seen.add(x.lower()); r.append(x)
        return r
    keep = lambda xs: [x for x in xs if not _GENERIC.search(x.lower())]   # drop generic from pre
    return {k: uniq(spec[k] + keep(pre[k])) for k in ("skills", "knowledge", "competencies")}


import hashlib
import os
from sqlalchemy import text
from ..domain.napoo import direction_vertical, best_direction
from ..data.models import Occupation

CACHE = "/Users/mdimitrov/.claude/drain-guardian/napoo-pdf"


def match_occupations(session_factory=SessionLocal, log=print) -> dict:
    """Attach each occupation to its best-matching ДОС direction (by NAME — matched on the ESCO
    Bulgarian label only, which is the clean signal; NKPD title variants inject noise). Reproducible:
    re-run after (re)parsing directions. Occupations with no name match fall back to the vertical."""
    for tbl in ("occupations", "profiles"):
        try:
            with engine.begin() as c:
                c.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS napoo_direction VARCHAR(255)"))
        except Exception:  # noqa: BLE001 — SQLite/create_all already has it
            pass
    with session_factory() as db:
        dirs = [(d.name, d.vertical) for d in db.execute(select(NapooDirection)).scalars()]
        occs = db.execute(select(Occupation)).scalars().all()
        matched = 0
        for i, o in enumerate(occs, 1):
            o.napoo_direction = best_direction([(o.labels or {}).get("bg", "")], o.vertical, dirs)
            matched += bool(o.napoo_direction)
            if i % 500 == 0:
                db.commit()
        db.commit()
    log(f"occupations matched to a direction: {matched}/{len(occs)}")
    return {"occupations_matched": matched, "total": len(occs)}


def _pdf_bytes(url: str):
    """Download once, cache on disk so re-parses (parser tweaks) don't re-fetch."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".pdf")
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        with open(path, "wb") as fh:
            fh.write(httpx.get(url, timeout=90, follow_redirects=True).content)
    return path


def run(session_factory=SessionLocal, only: str | None = None, log=print) -> dict:
    Base.metadata.create_all(bind=engine)   # creates napoo_directions if missing
    targets = [(n, u) for n, u in DIRECTIONS if not only or only.lower() in n.lower()]
    done = failed = skills = 0
    with session_factory() as db:
        existing = {d.url: d for d in db.execute(select(NapooDirection)).scalars()}
        for name, url in targets:
            try:
                res = parse_pdf(_pdf_bytes(url))
            except Exception as e:  # noqa: BLE001 — one bad PDF mustn't stop the batch
                failed += 1
                log(f"  FAIL {name}: {type(e).__name__}")
                continue
            row = existing.get(url) or NapooDirection(name=name, url=url)
            row.name, row.vertical = name, direction_vertical(name)
            row.skills, row.knowledge = res["skills"], res["knowledge"]
            db.add(row)
            db.commit()
            done += 1
            skills += len(res["skills"])
            log(f"  ok {name} [{row.vertical}]: {len(res['skills'])} умения")
    m = match_occupations(session_factory, log=log)   # per-profession direction match (reproducible)
    return {"directions_reparsed": done, "failed": failed, "total_skills": skills, **m}


if __name__ == "__main__":
    print(run(only=sys.argv[1] if len(sys.argv) > 1 else None))
