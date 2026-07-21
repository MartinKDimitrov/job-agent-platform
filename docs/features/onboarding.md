# Onboarding (light profile creation)

**What it does:** a ~30-second, mostly-click profile: the user picks their profession from a
Bulgarian-labelled list, gets that occupation's typical skills pre-checked as chips, unchecks
what doesn't fit, optionally adds more via native autocomplete, and a search profile is created
with Bulgaria-primary defaults (location "Bulgaria, Sofia, Varna" + remote, threshold 65%).
The full manual form remains available ("Use the full form").

**Modules**
- `domain/taxonomy.py` — curated occupation → skills seed (~23 IT occupations, BG+EN labels).
  Stage 2 swaps this for the full ESCO taxonomy (all professions) keeping the same shape.
- `presentation/routers/onboarding.py` — GET form (select + chip JS + datalist), POST create.

**Tests:** `tests/test_onboarding.py`.

**Rejected alternatives:** CV upload and LinkedIn data-export import (too much user effort);
LinkedIn OAuth alone gives only name/email, not skills.
