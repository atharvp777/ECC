"""Idempotent, lightweight database migrations.

This project deliberately has no Alembic or other migration framework.
``Base.metadata.create_all`` only creates missing tables — it never adds
columns to existing tables. These helpers add the handful of columns the
application has gained since the first release, guarded by ``PRAGMA
table_info`` so they are safe to run repeatedly on the live database.
"""

from sqlalchemy import text

# Columns added to the `tasks` table after the initial release.
# key = column name, value = ALTER TABLE ADD COLUMN clause.
_TASK_COLUMNS = {
    "google_calendar_event_id": "google_calendar_event_id VARCHAR(255)",
    "scheduled_start": "scheduled_start DATETIME",
    "scheduled_end": "scheduled_end DATETIME",
    "calendar_sync_error": "calendar_sync_error TEXT",
}


def run_idempotent_migrations(engine) -> None:
    """Add any missing `tasks` columns and their supporting index.

    SQLite cannot add a UNIQUE column via ``ALTER TABLE ... ADD COLUMN``, so
    uniqueness of ``google_calendar_event_id`` is enforced with a partial
    unique index instead (NULLs are always distinct in a SQLite unique index).

    This runs against whatever engine is bound — which is the repository-root
    ``ecc.db`` from ``settings.DATABASE_URL``, never a stray copy elsewhere.
    """
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(tasks)"))}
        for column, ddl in _TASK_COLUMNS.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {ddl}"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_google_calendar_event_id "
                "ON tasks(google_calendar_event_id)"
            )
        )
