# Status boards

Self-contained, theme-aware HTML snapshots of where the platform stands. Open any file in a
browser (no build, no assets).

| File | What it shows | Kind |
|------|---------------|------|
| [`implementation.html`](implementation.html) | End-to-end build map — 9 phases from foundation to launch, per-phase status, AI-cost strategy. Grounded in [`../../ROADMAP.md`](../../ROADMAP.md). | Snapshot — refresh when a phase changes |
| [`platform.html`](platform.html) | Collection system — volume, per-source breakdown, the aggregator pivot, roadmap. | Snapshot — refresh after a full ingest |
| [`adzuna-bulk-pull.html`](adzuna-bulk-pull.html) | Adzuna bulk-pull progress — category × country cursors, per-slice bars. | Generated: `python -m app.jobs adzuna_board <path>` |

The Adzuna board is regenerated from live cursors by `adzuna_bulk.render_board`; the committed
copy is a point-in-time snapshot. Numbers reflect staging at the last refresh (real data only).
