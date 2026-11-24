"""Database engine, session factory, and declarative base.

The engine is built from ``Settings.database_url``. SQLite is the zero-infra
default (useful for local runs and fast tests); Postgres is used when the URL
points at it. Code must not depend on the specific backend.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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


def build_engine(settings: Settings | None = None):
    """Create a SQLAlchemy engine for the configured database URL."""
    settings = settings or get_settings()
    connect_args: dict = {}
    if settings.database_url.startswith("sqlite"):
        # Required so the SQLite connection can be shared across threads in tests.
        connect_args["check_same_thread"] = False
    engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
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
