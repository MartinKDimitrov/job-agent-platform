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

**Tests:** `tests/test_dedup.py`.
