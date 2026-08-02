"""Additive schema sync: brings the live database up to date with the SQLAlchemy models.

Compares model metadata against the live database and applies only:
  - CREATE TABLE for any model with no matching table
  - ALTER TABLE ... ADD COLUMN IF NOT EXISTS for any column missing on an existing table

Never drops, renames, or alters an existing column or table. Safe to run repeatedly, and a
no-op against a database that's already fully in sync. Run after every deploy that changed
models.py, instead of hand-writing one-off ALTER TABLE commands.

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
        for name, table in Base.metadata.tables.items():
            if name not in live_tables:
                continue
            existing_columns = {c["name"] for c in inspector.get_columns(name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{name}" ADD COLUMN IF NOT EXISTS "{column.name}" {col_type}'
                conn.execute(text(ddl))
                print(f"added column: {name}.{column.name} ({col_type})")
                added_any = True

    if not missing_tables and not added_any:
        print("schema already up to date")
    print("schema sync complete")


if __name__ == "__main__":
    sync_schema()
