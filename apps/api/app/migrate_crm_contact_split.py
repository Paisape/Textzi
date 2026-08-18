"""One-off migration for the CRM Contact / WhatsApp Contact split (Addendum 8): Lead/Deal/
Customer/Task/Attachment currently point their contact_id at the WhatsApp-owned `contacts` table;
this creates the new `crm_contacts` table, copies a CrmContact row for every distinct contact
those 5 tables reference, links the originating WABA contact back via `contacts.crm_contact_id`,
and repoints the 5 tables' `contact_id` FK to `crm_contacts` instead.

Run this BEFORE `python -m app.sync_schema` on the deploy that ships the split -- sync_schema's
own additive logic can create the `crm_contacts` table but never repoints an existing FK
constraint, which is the one non-additive step only this script performs.

Safe to run only once -- re-running against an already-migrated database (contacts.crm_contact_id
already exists) is a no-op.

Usage: python -m app.migrate_crm_contact_split
"""
from sqlalchemy import inspect, text

from . import models  # noqa: F401  registers every model class on Base.metadata
from .database import Base, engine, SessionLocal
from .models import Attachment, Contact, CrmContact, Customer, Deal, Lead, Task


def migrate() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    if "contacts" not in existing_tables:
        print("nothing to migrate: no 'contacts' table exists yet (fresh database)")
        return
    contact_columns = {c["name"] for c in inspector.get_columns("contacts")}
    if "crm_contact_id" in contact_columns:
        print("already migrated: contacts.crm_contact_id exists, nothing to do")
        return

    if "crm_contacts" not in existing_tables:
        Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables["crm_contacts"]])
        print("created table: crm_contacts")

    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE "contacts" ADD COLUMN "crm_contact_id" VARCHAR(36)'))
        print("added column: contacts.crm_contact_id")
        # Drop the old FK constraints tying these 5 tables' contact_id to the WABA "contacts"
        # table -- they're about to point at "crm_contacts" instead, and the constraint would
        # otherwise reject every rewritten row below.
        for table in ("leads", "deals", "customers", "tasks", "attachments"):
            conn.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{table}_contact_id_fkey"'))
        print("dropped old contact_id FK constraints on leads/deals/customers/tasks/attachments")

    db = SessionLocal()
    try:
        old_to_new: dict[str, str] = {}
        migrated = 0
        for model in (Lead, Deal, Customer, Task, Attachment):
            for row in db.query(model).all():
                old_id = row.contact_id
                if old_id not in old_to_new:
                    waba_contact = db.get(Contact, old_id)
                    if waba_contact is None:
                        # Shouldn't happen (the old FK guaranteed it until we just dropped it),
                        # but a dangling reference shouldn't crash the whole migration.
                        continue
                    crm_contact = CrmContact(
                        entity_id=waba_contact.entity_id, name=waba_contact.name, phone=waba_contact.wa_id,
                        email=waba_contact.email, company_id=waba_contact.company_id, source="whatsapp_conversation",
                        consent_given_at=waba_contact.consent_given_at, consent_source=waba_contact.consent_source,
                    )
                    db.add(crm_contact)
                    db.flush()
                    waba_contact.crm_contact_id = crm_contact.id
                    old_to_new[old_id] = crm_contact.id
                    migrated += 1
                row.contact_id = old_to_new[old_id]
        db.commit()
        print(f"migrated {migrated} contact(s) into crm_contacts, repointed all referencing rows")
    finally:
        db.close()

    with engine.begin() as conn:
        for table in ("leads", "deals", "customers", "tasks", "attachments"):
            conn.execute(text(f'ALTER TABLE "{table}" ADD CONSTRAINT "{table}_contact_id_fkey" FOREIGN KEY ("contact_id") REFERENCES "crm_contacts"("id")'))
        print("added new contact_id FK constraints referencing crm_contacts")

    print("migration complete -- now run: python -m app.sync_schema")


if __name__ == "__main__":
    migrate()
