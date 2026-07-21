# SEO & i18n

**SEO:** every page gets title/description/canonical/robots/OG/Twitter meta via
`presentation/seo.py`. Pages are **noindex by default** — private (logged-in) screens can
never leak into search; only public pages opt in. `robots.txt` disallows the private areas;
`sitemap.xml` lists only public URLs. The public landing carries Organization/WebSite JSON-LD.
`JobPosting` structured data is deferred until public job pages exist (Phase 2/4).

**Public profession pages** (`presentation/routers/jobs_public.py`): `/jobs` (index), `/jobs/{occupation}` (EN) and `/bg/jobs/{occupation}` (BG), hreflang-paired, all in the sitemap. Content: live tracked-openings count, sample titles (title + company ONLY — descriptions and apply links never leak publicly; the value sits behind free registration), typical skills from the taxonomy, Q&A block, register CTA. Occupation→posting matching uses distinctive title tokens (generic role words like 'engineer' excluded). Tests: `tests/test_public_jobs.py`.

**i18n:** lightweight dict catalog (`presentation/i18n.py`, EN default + BG) with fallback
chain lang → en → key. Language resolution: explicit URL → `lang` cookie → `Accept-Language`
→ en. Public landing is language-prefixed (`/` en, `/bg` bg) with **hreflang** alternates +
x-default (both in the sitemap); login/register and the nav are localized; `/lang/{code}`
sets the cookie (same-site redirect only). Internal screens stay English for now.

**Modules:** `presentation/seo.py`, `presentation/routers/seo.py` (robots/sitemap),
`presentation/i18n.py`, `presentation/web.py` (shell integration), `core/config.py`
(`site_url` for absolute URLs).

**Tests:** `tests/test_seo.py`, `tests/test_i18n.py`.
