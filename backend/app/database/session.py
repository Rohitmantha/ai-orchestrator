"""
Async database session management.

FastAPI's routes are all `async def`, and the Orchestrator's engine is
async throughout -- so the DB layer underneath must be async too, or
every DB call would block the event loop. This means the `asyncpg`
driver (via `postgresql+asyncpg://` in the connection string), not the
synchronous `psycopg2` driver pip would otherwise default to.

Reads DATABASE_URL from the environment, matching the .env file set up
in Phase 1.5 -- never hardcode connection strings here.

IMPORTANT correction from an earlier version of this module: the async
engine was previously created ONCE at import time as a module-level
global, bound implicitly to whatever event loop happened to be running
the first time it was used. This breaks in any environment where more
than one event loop touches the engine over the process's lifetime --
which includes FastAPI's TestClient (each test can spin up its own
loop), BackgroundTasks running after the request's loop context has
moved on, and even some production ASGI server configurations. asyncpg
connections are not safe to hand between different event loops; the
failure mode is a cryptic "got Future attached to a different loop"
deep inside asyncpg's connection-close path.

The fix: the engine is created lazily, the first time `get_session()` or
`AsyncSessionLocal()`-equivalent access happens within a given loop, and
is cached per-loop (not globally) using a WeakKeyDictionary keyed by the
running loop. This is the documented-correct pattern for "one engine per
event loop" rather than "one engine, ever, globally."
"""

from __future__ import annotations

import asyncio
import os
import weakref

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engines_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncEngine]" = weakref.WeakKeyDictionary()


def _build_async_database_url() -> str:
    """The .env's DATABASE_URL is postgresql://... (the sync-style URL
    used by psql/Docker). SQLAlchemy's async engine needs the asyncpg
    driver named explicitly: postgresql+asyncpg://...
    This swap happens here, once per engine creation, rather than asking
    every caller to remember to do it."""
    raw_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://orchestrator:devpassword@localhost:5432/orchestrator_db",
    )
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw_url


def _get_engine_for_current_loop() -> AsyncEngine:
    loop = asyncio.get_event_loop()
    engine = _engines_by_loop.get(loop)
    if engine is None:
        engine = create_async_engine(_build_async_database_url(), echo=False, pool_pre_ping=True)
        _engines_by_loop[loop] = engine
    return engine


class _LoopAwareSessionFactory:
    """Callable that behaves like `async_sessionmaker(...)`'s instance
    (i.e. `AsyncSessionLocal()` still works exactly as before at every
    call site), but resolves the correct per-loop engine on each call
    instead of closing over one engine fixed at import time."""

    def __call__(self) -> AsyncSession:
        engine = _get_engine_for_current_loop()
        factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        return factory()


AsyncSessionLocal = _LoopAwareSessionFactory()


async def get_session() -> AsyncSession:
    """FastAPI dependency -- yields one session per request, closed
    automatically afterward. Used via `Depends(get_session)` in routers."""
    async with AsyncSessionLocal() as session:
        yield session


def get_engine() -> AsyncEngine:
    """Exposed mainly for tests that need direct engine access (e.g. to
    truncate tables between test runs) without going through a session.
    Resolves to the current loop's engine, same as everything else."""
    return _get_engine_for_current_loop()
