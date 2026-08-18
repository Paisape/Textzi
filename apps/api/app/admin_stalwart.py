"""Platform-admin visibility and control over Textzi-hosted CRM mailboxes (EmailAccount rows with
provider="stalwart", crm_mailserver.py) -- listing every provisioned mailbox across every tenant,
suspending/deleting one, and reading the actual mail sent/received through any of them.

Deliberately its own module (mirrors platform_admin.py's own "deliberately separate router"
reasoning), gated the same way admin.py's existing cross-tenant views are (require_admin +
require_admin_recent_2fa -- the precedent is admin.py's list_admin_messages/list_admin_api_log).

Full mail content is shown, not masked -- a deliberate difference from admin.py's SMS message log,
which masks because Textzi only routes through a third-party carrier's infrastructure there.
Textzi genuinely operates this mail server, so there's no third party's data being exposed by an
admin reading it; this is closer to "the person who runs the post office can see undelivered mail
still sitting in the sorting room" than "someone reading a stranger's private letters." Confirmed
as a deliberate choice with the user before building, not an oversight."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin import _caller_email, require_admin, require_admin_recent_2fa
from .database import get_db
from .models import Contact, Conversation, ConversationMessage, EmailAccount, Entity, Organization
from .schemas import AdminMailboxMessageOut, AdminMailboxOut, AdminMailboxStatusUpdateRequest
from .services import log_activity

router = APIRouter(prefix="/v1/admin/stalwart", tags=["admin-stalwart"], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])

MAILBOX_LOG_LIMIT = 200


def _org_names_for(db: Session, entity_ids: set[str]) -> tuple[dict[str, Entity], dict[str, str]]:
    entities = {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(entity_ids))).all()} if entity_ids else {}
    org_ids = {e.organization_id for e in entities.values()}
    org_names = {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all()} if org_ids else {}
    return entities, org_names


@router.get("/mailboxes", response_model=list[AdminMailboxOut])
def list_mailboxes(search: str | None = None, limit: int = MAILBOX_LOG_LIMIT, offset: int = 0, db: Session = Depends(get_db)):
    limit = max(1, min(limit, MAILBOX_LOG_LIMIT))
    offset = max(0, offset)
    query = select(EmailAccount).where(EmailAccount.provider == "stalwart").order_by(EmailAccount.created_at.desc())
    if search:
        query = query.where(EmailAccount.from_email.ilike(f"%{search}%"))
    accounts = db.scalars(query.limit(limit).offset(offset)).all()

    entities, org_names = _org_names_for(db, {a.entity_id for a in accounts})
    return [
        AdminMailboxOut(
            id=a.id,
            organization_name=org_names.get(entities[a.entity_id].organization_id) if a.entity_id in entities else None,
            entity_name=entities[a.entity_id].name if a.entity_id in entities else a.entity_id,
            address=a.from_email, status=a.status,
            last_synced_at=a.last_synced_at.isoformat() if a.last_synced_at else None,
            created_at=a.created_at.isoformat(),
        )
        for a in accounts
    ]


@router.patch("/mailboxes/{account_id}/status", response_model=AdminMailboxOut)
def update_mailbox_status(account_id: str, payload: AdminMailboxStatusUpdateRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Suspending sets status="suspended" -- send_email/poll_all_email_inboxes (crm_email.py) only
    ever act on status=="connected" rows, so a suspended mailbox silently stops sending/polling
    without deleting anything; the tenant's own Channels page will show it as broken, prompting
    them to reach out rather than data disappearing without a trace."""
    account = db.get(EmailAccount, account_id)
    if not account or account.provider != "stalwart":
        raise HTTPException(status_code=404, detail="Mailbox not found")
    account.status = payload.status
    entity = db.get(Entity, account.entity_id)
    log_activity(
        db, entity.organization_id if entity else None, "admin_mailbox_status_changed",
        f"Textzi-hosted mailbox {account.from_email} set to {payload.status} by an admin.",
        actor_email=_caller_email(authorization, db), request=request,
    )
    db.commit(); db.refresh(account)
    entities, org_names = _org_names_for(db, {account.entity_id})
    return AdminMailboxOut(
        id=account.id,
        organization_name=org_names.get(entities[account.entity_id].organization_id) if account.entity_id in entities else None,
        entity_name=entities[account.entity_id].name if account.entity_id in entities else account.entity_id,
        address=account.from_email, status=account.status,
        last_synced_at=account.last_synced_at.isoformat() if account.last_synced_at else None,
        created_at=account.created_at.isoformat(),
    )


@router.delete("/mailboxes/{account_id}")
def delete_mailbox(account_id: str, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Deletes only the EmailAccount row (Textzi's own record of the connection) -- does not call
    out to Stalwart to delete the mailbox/its mail there. Matches the tenant-side disconnect
    endpoint's own "detach, don't tear down" behavior (crm_email.py's disconnect_email_account) --
    an admin deleting the row here has the same effect a tenant disconnecting does, just done on
    their behalf; actually destroying mail on Stalwart is a separate, more deliberate action not
    exposed here."""
    account = db.get(EmailAccount, account_id)
    if not account or account.provider != "stalwart":
        raise HTTPException(status_code=404, detail="Mailbox not found")
    entity = db.get(Entity, account.entity_id)
    log_activity(
        db, entity.organization_id if entity else None, "admin_mailbox_deleted",
        f"Textzi-hosted mailbox {account.from_email} deleted by an admin.",
        actor_email=_caller_email(authorization, db), request=request,
    )
    db.delete(account)
    db.commit()
    return {"deleted": True}


@router.get("/messages", response_model=list[AdminMailboxMessageOut])
def list_mailbox_messages(entity_id: str | None = None, direction: str | None = None, limit: int = MAILBOX_LOG_LIMIT, offset: int = 0, db: Session = Depends(get_db)):
    limit = max(1, min(limit, MAILBOX_LOG_LIMIT))
    offset = max(0, offset)
    query = (
        select(ConversationMessage, Conversation)
        .join(Conversation, ConversationMessage.conversation_id == Conversation.id)
        .where(Conversation.channel == "email", ConversationMessage.is_private.is_(False))
        .order_by(ConversationMessage.created_at.desc())
    )
    if entity_id:
        query = query.where(Conversation.entity_id == entity_id)
    if direction:
        query = query.where(ConversationMessage.direction == direction)
    rows = db.execute(query.limit(limit).offset(offset)).all()

    entity_ids = {c.entity_id for _, c in rows}
    entities, org_names = _org_names_for(db, entity_ids)
    contact_ids = {c.contact_id for _, c in rows}
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_(contact_ids))).all()} if contact_ids else {}
    mailboxes = {a.entity_id: a for a in db.scalars(select(EmailAccount).where(EmailAccount.entity_id.in_(entity_ids), EmailAccount.provider == "stalwart")).all()}

    result = []
    for message, conversation in rows:
        entity = entities.get(conversation.entity_id)
        contact = contacts.get(conversation.contact_id)
        mailbox = mailboxes.get(conversation.entity_id)
        result.append(AdminMailboxMessageOut(
            id=message.id,
            organization_name=org_names.get(entity.organization_id) if entity else None,
            entity_name=entity.name if entity else conversation.entity_id,
            mailbox_address=mailbox.from_email if mailbox else "(disconnected)",
            direction=message.direction,
            contact_address=contact.email if contact else None,
            subject=(message.payload or {}).get("subject") if message.payload else None,
            body=message.body,
            created_at=message.created_at.isoformat(),
        ))
    return result
