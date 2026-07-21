"""Composition root: create the FastAPI app, add middleware, init the DB, mount routers.

The codebase follows Clean Architecture (see docs/architecture.md):
core → domain → data / application → presentation, with dependencies pointing inward.
Other entrypoints: app/jobs.py (cron daily digest), app/metrics.py (metrics CLI).
"""
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .core.config import settings
from .data.db import init_db
from .presentation.routers import auth, profiles, account, sources, seo, onboarding

app = FastAPI(title="Job Agent Platform")

# Session cookie is required by Authlib's OAuth flow (stores the state param).
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")


@app.on_event("startup")
def _startup():
    init_db()


app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(account.router)
app.include_router(sources.router)
app.include_router(seo.router)
app.include_router(onboarding.router)
