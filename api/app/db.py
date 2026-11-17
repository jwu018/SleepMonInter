"""Database connection: one engine for the process, one session per request.

- Engine: owns a small pool of open connections to Postgres, created once.
- Session: a unit of work (a few queries that belong together). Each request gets its own,
  and it is closed when the request ends, which returns the connection to the pool.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from .config import get_settings


class Base(DeclarativeBase):
    """Parent of every table class in models.py. Base.metadata lists all our tables."""


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Add it to api/.env (see .env.example).")
    # pool_pre_ping tests a pooled connection before using it, so a connection the server
    # closed while idle (Supabase does this) is replaced instead of causing an error.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: `db: Session = Depends(get_db)` gives a route its session."""
    with Session(get_engine()) as session:
        yield session


def get_session_factory() -> Callable[[], Session]:
    """FastAPI dependency for work that outlives the request (background processing).

    The request's own session closes when the response is sent, so a background job must
    open a new one. Tests override this to point at their in-memory database.
    """
    return lambda: Session(get_engine())
