"""make analysis timestamps NOT NULL (match the ORM models)

Migration 0005 created five timestamp columns as nullable while the models declare
them required (they are always filled by ``default=utcnow``):

    analysis_runs.started_at
    claim_entities.created_at
    alternative_explanations.created_at
    review_actions.created_at
    segment_reviews.created_at

SQLite cannot change NOT NULL in place, so each table is rebuilt with Alembic batch
mode (create new table, copy rows, drop old, rename). Rows, primary keys, foreign keys,
indexes, unique constraints and server defaults are carried over by reflection and
verified afterwards with PRAGMA foreign_key_check.

Foreign-key enforcement is NOT switched off. Instead the one parent-table hazard is
handled explicitly: ``claims.analysis_run_id`` references ``analysis_runs`` with
ON DELETE SET NULL, so when enforcement is on, dropping the old ``analysis_runs``
during the rebuild would null those links. The links are saved before the rebuild and
restored afterwards (ids are preserved by the copy), then checked. The other four
tables are not referenced by any table, so rebuilding them affects nothing else.

Existing NULLs: ``analysis_runs.started_at`` falls back to the row's own
``created_at`` (the moment the run row was recorded). For the four ``created_at``
columns there is no trustworthy source for a missing value, so the migration stops
with an error rather than inventing one.

Revision ID: 0006_analysis_not_null_ts
Revises: 0005_create_analysis
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_analysis_not_null_ts"
down_revision: str | None = "0005_create_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
COLUMNS: tuple[tuple[str, str], ...] = (
    ("analysis_runs", "started_at"),
    ("claim_entities", "created_at"),
    ("alternative_explanations", "created_at"),
    ("review_actions", "created_at"),
    ("segment_reviews", "created_at"),
)


def _saved_run_links(bind: sa.engine.Connection) -> list[tuple[str, str]]:
    return [
        (row[0], row[1])
        for row in bind.execute(
            sa.text("SELECT id, analysis_run_id FROM claims WHERE analysis_run_id IS NOT NULL")
        )
    ]


def _restore_run_links(bind: sa.engine.Connection, links: list[tuple[str, str]]) -> None:
    for claim_id, run_id in links:
        bind.execute(
            sa.text("UPDATE claims SET analysis_run_id = :run WHERE id = :id"),
            {"run": run_id, "id": claim_id},
        )
    still = {
        (r[0], r[1])
        for r in bind.execute(
            sa.text("SELECT id, analysis_run_id FROM claims WHERE analysis_run_id IS NOT NULL")
        )
    }
    if still != set(links):
        raise RuntimeError("claims.analysis_run_id links were not preserved; aborting")


def _check_foreign_keys(bind: sa.engine.Connection, tables: Sequence[str]) -> None:
    if bind.dialect.name != "sqlite":
        return
    for table in tables:
        problems = bind.execute(sa.text(f'PRAGMA foreign_key_check("{table}")')).fetchall()
        if problems:
            raise RuntimeError(f"foreign key violations in {table} after rebuild: {problems}")


def _set_nullable(nullable: bool) -> None:
    bind = op.get_bind()
    links = _saved_run_links(bind)
    for table, column in COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=TS, nullable=nullable)
    _restore_run_links(bind, links)
    _check_foreign_keys(bind, [t for t, _ in COLUMNS] + ["claims"])


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE analysis_runs SET started_at = created_at WHERE started_at IS NULL")
    )
    for table, column in COLUMNS[1:]:
        missing = bind.execute(
            sa.text(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NULL')
        ).scalar_one()
        if missing:
            raise RuntimeError(
                f"{missing} row(s) in {table} have no {column}; refusing to invent a value"
            )
    _set_nullable(False)


def downgrade() -> None:
    _set_nullable(True)
