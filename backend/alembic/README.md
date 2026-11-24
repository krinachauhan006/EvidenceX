Alembic migrations for EvidenceX.

Run against the database configured in the environment (see `backend/.env.example`):

    alembic upgrade head      # apply all migrations
    alembic downgrade -1      # revert the last migration

The URL and target metadata are supplied by the application (see `env.py`); no
connection string is stored in `alembic.ini`.
