"""Alembic environment.

The target metadata and the database URL both come from the application, so a
single source of truth drives both the app and migrations. Tests may supply a URL
through ``config.attributes["sqlalchemy_url"]`` to migrate a throwaway database.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.core.database import Base

# Import models so they register on Base.metadata.
from app.modules.analysis import models as _analysis_models  # noqa: F401
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.cases import models as _cases_models  # noqa: F401
from app.modules.evidence import models as _evidence_models  # noqa: F401
from app.modules.processing import models as _processing_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    # Keep the application's loggers alive when migrations run inside a process
    # that already configured logging (for example the test suite).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

_url = config.attributes.get("sqlalchemy_url") or get_settings().database_url
# ConfigParser treats "%" specially; escape it so URLs with encoded characters work.
config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
