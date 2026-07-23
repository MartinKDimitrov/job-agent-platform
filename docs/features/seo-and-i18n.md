# SEO & i18n

**SEO:** every page gets title/description/canonical/robots/OG/Twitter meta via
`presentation/seo.py`. Pages are **noindex by default** — private (logged-in) screens can
never leak into search; only public pages opt in. `robots.txt` disallows the private areas;
`sitemap.xml` lists only public URLs. The public landing carries Organization/WebSite JSON-LD.
`JobPosting` structured data is deferred until public job pages exist (Phase 2/4).

**Public profession pages** (`presentation/routers/jobs_public.py`): `/jobs` (index) and
`/jobs/{occupation}` in English, plus `/{lang}/jobs[/{occupation}]` for every other language —
hreflang-paired across all 13, all in the sitemap. Content: live tracked-openings count, sample
titles (title + company ONLY — descriptions and apply links never leak publicly; the value sits
behind free registration), typical skills from the taxonomy, Q&A block, register CTA.
Occupation→posting matching uses distinctive title tokens (generic role words like 'engineer'
excluded). Occupation display names fall back to English where the taxonomy has no localized
label. Tests: `tests/test_public_jobs.py`.

**i18n — 13 languages:** EN (default/fallback), BG, RO, DE, NL, FR, ES, RU, IT, EL, HR, PL, UK.
Catalogs live in `presentation/translations/` — one module per language, ~198 keys each (whole
UI + public SEO copy as `pub.*` keys); a parity test enforces identical key sets and format
placeholders across all catalogs, because a missing key silently falls back to English.
Fallback chain lang → en → key. Language resolution: explicit URL → `lang` cookie →
`Accept-Language` → en. Public landings are language-prefixed (`/` en, `/{lang}` otherwise)
with **hreflang** alternates + x-default (all in the sitemap). The header switcher is a native
`<select>` (13 languages); `/lang/{code}` sets the cookie (same-site redirect only) and
persists to the user's account so the digest email speaks the same language.

**Modules:** `presentation/seo.py`, `presentation/routers/seo.py` (robots/sitemap),
`presentation/i18n.py` + `presentation/translations/`, `presentation/web.py`
(shell integration), `core/config.py` (`site_url` for absolute URLs).

**Tests:** `tests/test_seo.py`, `tests/test_i18n.py`.
