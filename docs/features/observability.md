# Observability

**What it does:** every crawl run (daily job and each "Search now") records a `CrawlRun` row
with per-source fetch counts (and per-source errors) plus run totals: added, deduped,
filtered (hard filters), scored, matched, notified, emails_sent. Failures are recorded too
(`ok=False` + error text) — a run never disappears silently. A terminal report shows source
quality over time:

```
python -m app.metrics
#3 daily      2026-07-21 16:54 OK  matched=9 notified=1 added=34 deduped=6 filtered=17
       sources: greenhouse=733  dev_bg=10  remoteok=99  wwr=98  lever=175  ashby=121
```

**Modules:** `application/run_stats.py` (in-memory collector), `data/metrics_repo.py`
(persistence + report), `data/models.py` (`CrawlRun`), entrypoint `app/metrics.py`. The
search/digest use cases fill the collector; per-source error isolation lives in
`application/usecases/search.py` (`_safe`).

**Tests:** `tests/test_metrics.py`.
