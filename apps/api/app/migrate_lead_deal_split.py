"""One-off migration for the Lead/Deal split (Addendum 6): every existing `leads` row is already
deal-shaped (it had value/stage/pipeline_id/probability from creation), so this copies those rows
into a new `deals` table (preserving ids, so every existing FK into it keeps resolving correctly),
then drops the old wide `leads` table so `python -m app.sync_schema` can create a fresh, empty one
matching the new thin Lead model.

Note: `Base.metadata.create_all` runs on every API startup and already creates any *missing*
table (including an empty `deals`) the moment the API boots against the new models.py -- it never
touches an existing table, so the old `leads` table stays wide-shaped until this script runs. This
means `deals` may already exist (empty) by the time this script runs; that's fine, the copy below
is idempotent (ON CONFLICT DO NOTHING) either way.

Run this BEFORE `python -m app.sync_schema` on the deploy that ships the split -- sync_schema's
ADD COLUMN IF NOT EXISTS is what adds deal_id/priority/outcome to tasks and quotes/
sequence_enrollments/customers, which this script's column renames below depend on running first.

Safe to run only once -- re-running against an already-migrated database is a no-op.

Usage: python -m app.migrate_lead_deal_split
"""
from sqlalchemy import inspect, text

from . import models  # noqa: F401  registers every model class on Base.metadata
from .database import Base, engine


def migrate() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    if "leads" not in existing_tables:
        print("nothing to migrate: no 'leads' table exists yet (fresh database)")
        return

    lead_columns = {c["name"] for c in inspector.get_columns("leads")}
    if "value" not in lead_columns:
        print("'leads' table is already thin-shaped, nothing to do")
        return

    if "deals" not in existing_tables:
        Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables["deals"]])
        print("created table: deals")
        existing_tables.add("deals")

    with engine.begin() as conn:
        moved = conn.execute(text("""
            INSERT INTO deals (
                id, entity_id, contact_id, pipeline_id, stage, source, converted_from_conversation_id,
                owner_user_id, notes, value, probability, expected_close_date, status, lost_reason,
                custom_fields, created_at
            )
            SELECT
                id, entity_id, contact_id, pipeline_id, stage, source, converted_from_conversation_id,
                owner_user_id, notes, value, probability, expected_close_date, status, lost_reason,
                COALESCE(custom_fields, '{}'::json), created_at
            FROM leads
            ON CONFLICT (id) DO NOTHING
        """))
        print(f"copied {moved.rowcount} row(s): leads -> deals")

        for table, column in (("quotes", "lead_id"), ("sequence_enrollments", "lead_id"), ("customers", "lead_id")):
            if table in existing_tables and column in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f'ALTER TABLE "{table}" RENAME COLUMN "{column}" TO "deal_id"'))
                print(f"renamed column: {table}.{column} -> deal_id")

        # CASCADE drops the FK constraint deals.converted_from_lead_id has on this table, not the
        # deals table itself -- deals rows are untouched, just left without that constraint until
        # sync_schema re-adds it once the fresh, thin "leads" table exists again below.
        conn.execute(text('DROP TABLE "leads" CASCADE'))
        print("dropped table: leads (will be recreated thin-shaped by sync_schema)")

    print("migration complete -- now run: python -m app.sync_schema")


if __name__ == "__main__":
    migrate()
