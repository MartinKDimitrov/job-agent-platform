# Auth & Accounts

**What it does:** email+password registration/login (bcrypt, JWT in an httpOnly cookie) and
"Sign in with Google" (OAuth via Authlib; inactive until `GOOGLE_CLIENT_ID/SECRET` are set —
degrades to a friendly message). GDPR self-service: JSON data export and type-to-confirm
account deletion (cascades profiles → matches, applications, sources). An "I found a job"
toggle pauses the user's daily searches.

**Modules**
- `presentation/routers/auth.py` — landing/dashboard, register/login/logout, Google OAuth flow.
- `presentation/routers/account.py` — account page, export, delete, found-job toggle.
- `data/security.py` — bcrypt hashing (72-byte cap) + JWT make/read.
- `data/activity_repo.py` — found-job flag persistence; `presentation/web.py` `current_user`
  also records last-seen activity (throttled).

**Tests:** `tests/test_auth.py`, `tests/test_account.py`, `tests/test_activity.py`.
