"""Additive schema sync: brings the live database up to date with the SQLAlchemy models.

Compares model metadata against the live database and applies only:
  - CREATE TABLE for any model with no matching table
  - ALTER TABLE ... ADD COLUMN IF NOT EXISTS for any column missing on an existing table
  - CREATE INDEX IF NOT EXISTS for any named Index in a model's __table_args__ missing on an
    existing table (a brand new table already gets its indexes from CREATE TABLE above; this
    step is only for adding a new index to a table that already exists)

Never drops, renames, or alters an existing column, index, or table. Safe to run repeatedly, and
a no-op against a database that's already fully in sync. Run after every deploy that changed
models.py, instead of hand-writing one-off ALTER TABLE/CREATE INDEX commands.

Usage: python -m app.sync_schema
"""
from sqlalchemy import inspect, text

from . import models  # noqa: F401  registers every model class on Base.metadata
from .database import Base, engine


def sync_schema() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    missing_tables = [
        table for name, table in Base.metadata.tables.items()
        if name not in existing_tables
    ]
    if missing_tables:
        Base.metadata.create_all(bind=engine, tables=missing_tables)
        for table in missing_tables:
            print(f"created table: {table.name}")
        inspector = inspect(engine)

    added_any = False
    live_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        # Reflect columns/indexes through THIS transaction's own connection, not a fresh
        # Inspector bound to a separate connection -- confirmed as a real, reproducible deadlock:
        # inspect(engine) opens a new connection per call, and Postgres's own catalog-introspection
        # queries (pg_index/pg_am joins) take an AccessShareLock that queues behind this loop's own
        # uncommitted ALTER TABLE (an AccessExclusiveLock) on a table already touched earlier in
        # the same loop -- the transaction can never finish reflecting the next table because it's
        # waiting on a lock its own earlier, still-open DDL is holding. Using conn's own inspector
        # keeps every read inside the same transaction/connection as the writes, so there's no
        # second connection to ever block against.
        conn_inspector = inspect(conn)
        for name, table in Base.metadata.tables.items():
            if name not in live_tables:
                continue
            existing_columns = {c["name"] for c in conn_inspector.get_columns(name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{name}" ADD COLUMN IF NOT EXISTS "{column.name}" {col_type}'
                conn.execute(text(ddl))
                print(f"added column: {name}.{column.name} ({col_type})")
                added_any = True
                # Rows that existed before this column did get NULL here regardless of the
                # model's Python-side `default=` -- that only ever fires on INSERT through the
                # ORM, never for rows added via this raw ALTER TABLE. Left unfixed, the first
                # read of any such row throws a Pydantic validation error the moment a response
                # schema declares the field as a required (non-Optional) type -- confirmed live
                # against Conversation.is_ticket. Only backfills for a plain scalar default
                # (bool/str/int literals), not a callable (e.g. uid()) or a DB sequence, since
                # those need a value generated per-row, not one shared constant.
                if column.default is not None and column.default.is_scalar:
                    conn.execute(text(f'UPDATE "{name}" SET "{column.name}" = :default WHERE "{column.name}" IS NULL'), {"default": column.default.arg})

            existing_indexes = {idx["name"] for idx in conn_inspector.get_indexes(name)}
            for index in table.indexes:
                if not index.name or index.name in existing_indexes:
                    continue
                columns = ", ".join(f'"{c.name}"' for c in index.columns)
                ddl = f'CREATE INDEX IF NOT EXISTS "{index.name}" ON "{name}" ({columns})'
                conn.execute(text(ddl))
                print(f"added index: {index.name} on {name} ({columns})")
                added_any = True

    if not missing_tables and not added_any:
        print("schema already up to date")
    print("schema sync complete")


if __name__ == "__main__":
    sync_schema()
