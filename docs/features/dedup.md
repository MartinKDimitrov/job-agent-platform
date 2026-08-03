# Cross-source Deduplication

**What it does:** the same job listed on dev.bg, JobTiger and a company's ATS board lands as
**one** posting. Two layers at ingest time:
1. `content_hash` — URL-based identity (same source seen again → skipped).
2. Cross-source — same **normalized employer** (Cyrillic→Latin transliteration, legal suffixes
   ЕАД/ООД/Ltd/… dropped, light phonetic squash so "ПроКредит" == "ProCredit") **and**
   same/near-identical title (token Jaccard ≥ 0.6, developer/dev/programmer ≡ engineer
   synonyms; seniority tokens keep Senior ≠ Junior).

When the duplicate arrives from an **ATS** (canonical apply URL), the stored posting's
`apply_url` is upgraded to it — aggregator links never win over the ATS (agent A5).

**Modules:** `domain/dedup.py` (pure normalization/similarity), `data/ingest.py` (application
at persistence time; in-memory index per call — a persisted `dedup_key` column arrives with
Alembic, ROADMAP step 35).

**Retroactive sweep** (`merge_near_duplicates`, run by hand after big drains): stage 0 retires
EXACT duplicates already in the index — same lowercased title + same `md5(description)` (computed
server-side on Postgres, dialect-safe on SQLite), same-or-empty company only, since aggregator
redirects arrive company-less; one hygiene run retired 37,469 aggregator copies. Retirements go
out in **1000-id chunked UPDATEs** — per-row updates over the tunnel stalled 25+ minutes (same
lesson as everywhere: batch everything that crosses the tunnel).

**Batched persistence (perf).** Under the bulk drains every DB round-trip crosses the flaky
staging tunnel, so `ingest()` is round-trip-frugal: both the cross-source candidate load and the
`content_hash` existence check are single `IN(...)` queries per page (not per posting), and the
batch's brand-new rows are inserted in **one bulk flush** rather than a SAVEPOINT+flush each. The
`content_hash` UNIQUE still guards against the parallel drains (`adzuna_fast` + `careerjet_fast`
write at once): the bulk flush runs inside a savepoint and, only on a genuine concurrent collision,
falls back to per-row inserts — survivors persist, the racing winner is touched. This took a page's
persist from ~200 sequential round-trips to a handful.

**Tests:** `tests/test_dedup.py` (incl. the concurrent-collision fallback).
