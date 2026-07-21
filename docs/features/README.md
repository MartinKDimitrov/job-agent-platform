# Feature Docs

One file per functionality: what it does + which modules implement it. Update the relevant
file in the same change that alters behaviour (required — see CLAUDE.md §5).

- [auth-and-accounts.md](auth-and-accounts.md) — register/login, Google OAuth, GDPR export/delete, found-job pause
- [onboarding.md](onboarding.md) — occupation-first light profile creation
- [search-and-scoring.md](search-and-scoring.md) — the Search-now pipeline, hard filters, scoring
- [sources-and-adapters.md](sources-and-adapters.md) — the job sources and the one-adapter-per-source rule
- [dedup.md](dedup.md) — cross-source deduplication
- [daily-digest.md](daily-digest.md) — daily background search + email notifications
- [observability.md](observability.md) — per-run/per-source metrics
- [seo-and-i18n.md](seo-and-i18n.md) — SEO foundation and BG/EN localization

Product-level design lives at the repo root: `ARCHITECTURE.md` (agents/phases),
`DECISIONS.md`, `ROADMAP.md`, `LLM_COST_STRATEGY.md`. Code-level architecture:
[../architecture.md](../architecture.md).
