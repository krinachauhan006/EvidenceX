"""Database schema revision: what the database has vs. what this code expects.

Used to report a pending migration clearly (``/health`` and a 503 with an actionable
message) instead of an opaque 500 when the code runs against an older database. It
only reads; it never migrates.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

BACKEND_DIR = Path(__file__).resolve().parents[2]


def migrations_dir() -> Path | None:
    """The folder holding ``alembic.ini`` and ``alembic/``.

    Normally next to the ``app`` package (a source checkout, the Docker image). When the
    project is also pip-installed (as hosting platforms may do), ``app`` can be imported
    from site-packages, where the migration scripts are not; the deployment's working
    directory (its project root) is then checked."""
    for candidate in (BACKEND_DIR, Path.cwd()):
        if (candidate / "alembic.ini").is_file() and (candidate / "alembic").is_dir():
            return candidate
    return None


SCHEMA_OUTDATED_MESSAGE = (
    "The EvidenceX database is older than this version of the server, so this action "
    "cannot run yet. An administrator must back up the database and then run "
    "'alembic upgrade head' in the backend folder."
)


@lru_cache(maxsize=1)
def expected_revision() -> str | None:
    """The newest Alembic revision shipped with this code (None if unreadable)."""
    root = migrations_dir()
    if root is None:
        return None
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "alembic"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001 - reporting aid only; never breaks a request
        return None


def database_revision(engine: Engine) -> str | None:
    """The revision recorded in the database, or None (no Alembic table / no row)."""
    with engine.connect() as conn:
        if not inspect(conn).has_table("alembic_version"):
            return None
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        return str(row[0]) if row else None


def schema_state(engine: Engine) -> dict[str, object]:
    """``{"revision", "expected", "up_to_date"}``. ``up_to_date`` is None when either
    side is unknown (e.g. a database created without Alembic, as in the test suite)."""
    try:
        current = database_revision(engine)
    except SQLAlchemyError:
        current = None
    expected = expected_revision()
    up_to_date = None if current is None or expected is None else current == expected
    return {"revision": current, "expected": expected, "up_to_date": up_to_date}


# Errors that mean "the table or column this code needs does not exist".
_MISSING_SCHEMA_MARKERS = ("no such table", "no such column", "undefinedtable", "undefinedcolumn")
_MISSING_SCHEMA_PGCODES = {"42P01", "42703"}  # undefined_table, undefined_column


def is_missing_schema_error(exc: SQLAlchemyError) -> bool:
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) in _MISSING_SCHEMA_PGCODES:
        return True
    if getattr(orig, "pgcode", None) in _MISSING_SCHEMA_PGCODES:
        return True
    text_ = f"{type(orig).__name__} {orig}".lower()
    return any(m in text_ for m in _MISSING_SCHEMA_MARKERS)
