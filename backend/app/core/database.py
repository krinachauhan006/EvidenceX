"""Database engine, session factory, and declarative base.

The engine is built from ``Settings.database_url``. SQLite is the zero-infra
default (useful for local runs and fast tests); Postgres is used when the URL
points at it. Code must not depend on the specific backend.

The engine is created once per process (module import), so requests reuse pooled
connections instead of opening one each. For Postgres the pool is small, checks a
connection before use (``pool_pre_ping``) and recycles connections that managed
databases may have closed. Behind a transaction-mode pooler the client keeps no pool
of its own and psycopg's prepared statements are turned off.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _enable_sqlite_fk(engine: Engine) -> None:
    """SQLite ignores foreign keys (and ON DELETE CASCADE) unless the pragma is
    enabled per connection. Postgres enforces them natively, so this is a no-op
    there."""
    if engine.dialect.name != "sqlite":
        return

    # Background extraction jobs write while request threads read. A busy timeout
    # makes writers wait instead of failing with "database is locked", and WAL lets
    # readers continue while a writer is active. WAL only applies to file databases.
    is_memory = engine.url.database in (None, "", ":memory:")

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        if not is_memory:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def engine_options(settings: Settings) -> dict[str, Any]:
    """Keyword arguments for ``create_engine`` for the configured database."""
    url = settings.database_url
    if url.startswith("sqlite"):
        # Required so the SQLite connection can be shared across threads in tests.
        return {"connect_args": {"check_same_thread": False}}
    options: dict[str, Any] = {"pool_pre_ping": True}
    if settings.database_transaction_pooler:
        # The pooler is the pool; a client-side pool would pin server connections.
        options["poolclass"] = NullPool
        if url.startswith("postgresql+psycopg"):
            # Transaction poolers may hand each transaction a different server
            # session, so prepared statements must not be used (psycopg docs).
            options["connect_args"] = {"prepare_threshold": None}
    else:
        options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
    return options


def build_engine(settings: Settings | None = None):
    """Create a SQLAlchemy engine for the configured database URL."""
    settings = settings or get_settings()
    engine = create_engine(settings.database_url, future=True, **engine_options(settings))
    _enable_sqlite_fk(engine)
    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
