"""App wiring: create the FastAPI app, add middleware, init the DB on startup, mount routers.

Kept intentionally thin — features live in `app/routers/<feature>.py` and shared layout in
`app/web.py`, so a change touches a small module (see CLAUDE.md §5, "Modular by default").
"""
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import init_db
from .routers import auth, profiles, account, sources

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
