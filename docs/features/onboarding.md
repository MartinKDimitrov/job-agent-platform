# Onboarding (light profile creation)

**What it does:** a ~30-second, mostly-click profile. A multi-step wizard: (1) general info
(country/city dependent dropdowns, work mode, English CEFR, languages as chips), (2) a professional
field, (3) the specific occupation via an accordion of ISCO groups (+ free-text search), (4) its
typical skills pre-checked as chips (essential/optional split, per-skill years or "courses-only"),
with a bulk-years shortcut. A search profile is created with Bulgaria-primary defaults (threshold
65%). Fully responsive + theme-aware; the clickable stepper jumps between reached steps.

**Taxonomy backbone — ESCO (multilingual).** The picker is driven by the full **ESCO** taxonomy:
`occupation_groups` (ISCO hierarchy) → `occupations` (~2,900 professions, labels as `{lang: label}`)
→ `taxonomy_skills` / `occupation_skills` (essential/optional). Multilingual (BG/EN + EU languages),
so it serves every one of the platform's UI languages. Loaded by `app.tools.import_esco` (the
traversal recurses occupation→sub-occupation nesting to reach the full set, not just ISCO leaves).

**Bulgarian NKPD overlay (BG market only).** Each occupation also carries its official
**НКПД-2011** positions + qualification level (`Occupation.nkpd = [{code, title, level, rel}]`),
joined from the MLSP NKPD↔ESCO correspondence table by Bulgarian label (98% coverage). For `lang=bg`
the occupation picker shows a **"ниво N" badge** (min education/qualification level, 0–8) and the
official NKPD title when it differs from the ESCO label. ESCO stays the backbone; NKPD only enriches
Bulgarian. Loaded by `app.tools.import_nkpd`. The chosen level is stored on the profile
(`Profile.qualification_level`) and used by matching — see [search-and-scoring](search-and-scoring.md).

**НАПОО ДОС competencies (BG display/CV overlay).** The official vocational-education state
standards (`NapooDirection`, 144 professional directions, ~15.8k field-specific знания/умения/
компетенции). The ДОС PDF parse is **specific-first**: the profession-SPECIFIC section (found at the
*last* "специфична … по професията" header — the first is only the structure description) is emitted
before the shared обща+отраслова foundation, and the generic safety/entrepreneurship units are
dropped from that foundation — so a welder's list leads with МИГ/МАГ заваряване, not the common
technical-drawing base. Each occupation is name-matched to its specific direction (63%; e.g.
заварчик→"Технологии и системи за заваряване", the rest fall back to the vertical-wide set), stored
as `Occupation.napoo_direction` → copied to `Profile.napoo_direction` at onboarding. The BG profile page shows an "Официални компетенции (НАПОО)"
panel and BG CV/cover-letter prompts get them as reference vocabulary (never as claimed skills).
Descriptive, so display/CV only — not matching. Loaded by `app.tools.import_napoo`.

**Modules**
- `data/taxonomy_repo.py` — the read queries the picker drills through (verticals → groups →
  occupations → skills); `occupations()` surfaces the NKPD level + official title for `bg`.
- `presentation/routers/onboarding.py` — GET wizard (inline CSS/JS, custom dropdowns, language +
  skill pickers) + JSON endpoints (`/api/subcats|occupations|search|skills|cities`) + POST create.
- `app.tools.import_esco`, `app.tools.import_nkpd`, `app.tools.import_cities` (GeoNames gazetteer).

**Tests:** `tests/test_onboarding.py`, `tests/test_profiles.py`.

**Rejected alternatives:** CV upload and LinkedIn data-export import (too much user effort);
LinkedIn OAuth alone gives only name/email, not skills. Scraping a private job board's taxonomy —
against ToS and our own no-scrape rule; the official public NKPD/ESCO sources cover it legally.
