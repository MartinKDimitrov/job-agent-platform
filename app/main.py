"""Composition root: create the FastAPI app, add middleware, init the DB, mount routers.

The codebase follows Clean Architecture (see docs/architecture.md):
core → domain → data / application → presentation, with dependencies pointing inward.
Other entrypoints: app/jobs.py (cron daily digest), app/metrics.py (metrics CLI).
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .core.config import settings
from .data.db import init_db
from .presentation.routers import (auth, profiles, account, sources, seo, onboarding,
                                    documents, jobs_public)

app = FastAPI(title="Job Agent Platform")

# Session cookie is required by Authlib's OAuth flow (stores the state param).
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")

# Design system stylesheet + any future static assets (Lovable-produced design.css).
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "presentation" / "static"),
          name="static")


@app.on_event("startup")
def _startup():
    init_db()
    # DB-first search: the index refreshes in the background (INGEST_EVERY_HOURS, 0=off);
    # Search now never fetches. Cron-managed deployments run `python -m app.jobs ingest` instead.
    from .data.db import SessionLocal
    from .application.usecases.ingest_job import start_background_ingester
    start_background_ingester(SessionLocal)


app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(account.router)
app.include_router(sources.router)
app.include_router(seo.router)
app.include_router(onboarding.router)
app.include_router(documents.router)
app.include_router(jobs_public.router)
