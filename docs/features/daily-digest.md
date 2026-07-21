# Daily Digest

**What it does:** once a day (cron: `python -m app.jobs`) the system fetches all sources
**once**, then for every **active** user with profiles scores the batch and emails only the
**new** matches above their threshold. Never re-notifies the same match (`DigestEntry` marks
sent pairs). Users are skipped when they toggled **"I found a job"** or haven't been seen in
the last **5 days** (`UserActivity.last_seen_at`, touched on authenticated requests).

Email goes through SMTP when configured (`SMTP_HOST` etc. in env); otherwise dev-mode logs the
message so the whole flow is exercisable without an email account. The slow JobTiger source
(30s crawl delay) is included only here via `jobtiger_limit` (cron uses 20 pages/run).

**Modules:** `application/usecases/digest.py` (orchestration + email composition),
`data/mailer.py`, `domain/activity_rules.py` + `data/activity_repo.py` (gating),
`data/models.py` (`DigestEntry`, `UserActivity`), entrypoint `app/jobs.py`.

**Tests:** `tests/test_jobs.py`.
