"""Customer-facing shared inbox: conversations, contacts, labels, canned responses. Reads/writes
the tables added for the native WhatsApp inbox (models.py's "Native shared inbox" section) --
deliberately its own module, never importing from or importing into dispatch.py/providers.py/
webhooks.py (the SMS-specific pipeline), same isolation principle as every other WABA module."""
import mimetypes
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
import csv
import io
import secrets

from .models import (
    AutomationRule, BusinessHours, CannedResponse, Contact, ContactLabel, Conversation, ConversationLabel, ConversationMessage,
    CrmContact, CsatResponse, CsatSettings, Customer, Deal, Label, Lead, Macro, Segment, SlaPolicy, TicketGroup, User,
    WabaConnection, WabaWebhookSubscription,
)
from .schemas import (
    AgentCapacityUpdateRequest, AssignableUserOut, AutomationRuleCreateRequest, AutomationRuleOut, BusinessHoursOut, BusinessHoursUpdateRequest,
    CannedResponseCreateRequest, CannedResponseOut, ContactDirectoryEntryOut, ContactMessageRequest, ContactOut, ContactTimelineOut, ContactUpdateRequest,
    ConversationCcUpdateRequest, ConversationCountsOut, ConversationDetailOut, ConversationMessageCreateRequest, ConversationMessageOut,
    ConversationOut, ConversationSubjectUpdateRequest, ConversationUpdateRequest,
    CrmContactOut, CsatSettingsOut, CsatSettingsUpdateRequest, CustomerOut, DealOut, InteractiveButtonRequest, InteractiveListRequest, ProductMessageRequest,
    LabelCreateRequest, LabelOut, LeadOut, LocationMessageRequest, MacroCreateRequest, MacroOut, ReactionRequest, SegmentCreateRequest,
    SegmentOut, SlaPolicyOut, SlaPolicyUpdateRequest, StartConversationRequest, TemplateButtonOut, TemplateCreateRequest,
    TemplateMessageRequest, TicketCategoryUpdateRequest, TicketCountsOut, TicketCustomFieldsUpdateRequest, TicketGroupAssignRequest,
    TicketGroupCreateRequest, TicketGroupOut, TicketPriorityUpdateRequest, TicketSummary, WabaTemplateOut, WabaWebhookSubscriptionOut,
    WabaWebhookSubscriptionUpdateRequest,
)
from . import waba_media
from .permissions import require_channel_scope_any
from .security import decrypt_secret
from .services import DomainError, channel_active, get_platform_waba_settings, resolve_user_entity
from .waba_dispatch import (
    mark_conversation_read, send_whatsapp_contact, send_whatsapp_interactive_buttons, send_whatsapp_interactive_list,
    send_whatsapp_location, send_whatsapp_media, send_whatsapp_product, send_whatsapp_reaction, send_whatsapp_template, send_whatsapp_text,
)
from .waba_meta import MetaApiError, create_message_template, delete_message_template, list_message_templates, upload_template_header_media
from .waba_realtime import authenticate_query_token, message_payload, publish_event

# Shared inbox module -- owns the Conversation/Task/ticket tables both the plain WhatsApp inbox
# AND CRM's Tickets/Email/Helpdesk pages call directly, so this is gated to either channel
# scope, not "waba" alone (unlike waba.py/waba_campaigns.py/waba_reports.py, which really are
# WhatsApp-only and stay single-channel gated).
router = APIRouter(prefix="/v1/waba", tags=["waba-inbox"], dependencies=[Depends(require_channel_scope_any(["waba", "crm"]))])


def _labels_for(db: Session, assoc_model, key_column, key_value: str) -> list[LabelOut]:
    labels = db.scalars(select(Label).join(assoc_model, assoc_model.label_id == Label.id).where(key_column == key_value)).all()
    return [LabelOut(id=label.id, scope=label.scope, name=label.name, color=label.color) for label in labels]


def _contact_out(db: Session, contact: Contact) -> ContactOut:
    return ContactOut(
        id=contact.id, wa_id=contact.wa_id, email=contact.email, name=contact.name,
        custom_attributes=contact.custom_attributes or {}, opted_out=contact.opted_out,
        labels=_labels_for(db, ContactLabel, ContactLabel.contact_id, contact.id),
        company_id=contact.company_id,
        consent_given_at=contact.consent_given_at.isoformat() if contact.consent_given_at else None,
        consent_source=contact.consent_source, crm_contact_id=contact.crm_contact_id, created_at=contact.created_at.isoformat(),
    )


def _crm_contact_out(contact: CrmContact) -> CrmContactOut:
    return CrmContactOut(
        id=contact.id, name=contact.name, phone=contact.phone, email=contact.email, title=contact.title,
        company_id=contact.company_id, source=contact.source, custom_fields=contact.custom_fields or {},
        consent_given_at=contact.consent_given_at.isoformat() if contact.consent_given_at else None,
        consent_source=contact.consent_source, created_at=contact.created_at.isoformat(),
    )


def _conversation_out(db: Session, conversation: Conversation, contact: Contact, latest_message: ConversationMessage | None = None) -> ConversationOut:
    unread = bool(conversation.last_message_at and (not conversation.last_read_at or conversation.last_read_at < conversation.last_message_at))
    preview = None
    if latest_message:
        preview = latest_message.body if latest_message.body else f"[{latest_message.message_type}]"
        if latest_message.is_private:
            preview = f"Note: {preview}"
    # Computed at read time rather than a background job -- a breach only needs to be visible
    # when someone's actually looking, and this avoids a scheduled task for what's fundamentally
    # a "is this timestamp in the past" check.
    is_breached = bool(conversation.first_response_due_at and conversation.first_response_due_at < datetime.now(timezone.utc))
    if is_breached and not conversation.sla_breached:
        conversation.sla_breached = True
    is_resolution_breached = bool(conversation.resolution_due_at and conversation.resolution_due_at < datetime.now(timezone.utc) and conversation.status != "resolved")
    if is_resolution_breached and not conversation.resolution_breached:
        conversation.resolution_breached = True
    return ConversationOut(
        id=conversation.id, contact=_contact_out(db, contact), channel=conversation.channel, status=conversation.status,
        assigned_user_id=conversation.assigned_user_id,
        last_message_at=conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        last_read_at=conversation.last_read_at.isoformat() if conversation.last_read_at else None,
        last_message_preview=preview[:160] if preview else None,
        unread=unread,
        is_ticket=bool(conversation.is_ticket),
        ticket_number=conversation.ticket_number,
        created_at=conversation.created_at.isoformat(),
        labels=_labels_for(db, ConversationLabel, ConversationLabel.conversation_id, conversation.id),
        first_response_due_at=conversation.first_response_due_at.isoformat() if conversation.first_response_due_at else None,
        sla_breached=conversation.sla_breached,
        resolution_due_at=conversation.resolution_due_at.isoformat() if conversation.resolution_due_at else None,
        resolution_breached=conversation.resolution_breached,
        priority=conversation.priority,
        category=conversation.category,
        group_id=conversation.group_id,
        ticket_custom_fields=conversation.ticket_custom_fields or {},
        subject=conversation.subject,
        cc_emails=conversation.cc_emails or [],
    )


def _latest_messages_for(db: Session, conversation_ids: list[str]) -> dict[str, ConversationMessage]:
    """One most-recent message per conversation, in a single query -- Postgres' DISTINCT ON,
    rather than N+1 per-conversation lookups or pulling every message in these conversations
    just to keep the last one in Python."""
    if not conversation_ids:
        return {}
    rows = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id.in_(conversation_ids))
        .distinct(ConversationMessage.conversation_id)
        .order_by(ConversationMessage.conversation_id, ConversationMessage.created_at.desc()),
    ).all()
    return {m.conversation_id: m for m in rows}


def _message_out(message: ConversationMessage) -> ConversationMessageOut:
    return ConversationMessageOut(
        id=message.id, direction=message.direction, is_private=message.is_private, message_type=message.message_type,
        body=message.body, media_url=message.media_url, payload=message.payload, status=message.status, error=message.error,
        sent_by_user_id=message.sent_by_user_id, created_at=message.created_at.isoformat(),
    )


def _get_owned_conversation(db: Session, entity_id: str, conversation_id: str) -> tuple[Conversation, Contact]:
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.entity_id == entity_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    contact = db.get(Contact, conversation.contact_id)
    return conversation, contact


def _get_owned_label(db: Session, entity_id: str, label_id: str) -> Label:
    label = db.get(Label, label_id)
    if not label or label.entity_id != entity_id:
        raise HTTPException(status_code=404, detail="Label not found")
    return label


# --- Conversations ---------------------------------------------------------------------------

@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    status: str | None = None, assigned_user_id: str | None = None, assignment: str | None = None, label_id: str | None = None, search: str | None = None,
    is_ticket: bool | None = None, channel: str | None = None,
    limit: int = 50, offset: int = 0, user: User = Depends(require_user), db: Session = Depends(get_db),
):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    limit = max(1, min(limit, 200))
    query = select(Conversation).where(Conversation.entity_id == entity.id)
    if channel:
        query = query.where(Conversation.channel == channel)
    if status:
        query = query.where(Conversation.status == status)
    if is_ticket is not None:
        query = query.where(Conversation.is_ticket == is_ticket)
    if assigned_user_id:
        query = query.where(Conversation.assigned_user_id == assigned_user_id)
    if assignment == "unassigned":
        query = query.where(Conversation.assigned_user_id.is_(None))
    elif assignment == "mine":
        query = query.where(Conversation.assigned_user_id == user.id)
    if label_id:
        query = query.join(ConversationLabel, ConversationLabel.conversation_id == Conversation.id).where(ConversationLabel.label_id == label_id)
    if search:
        like = f"%{search.strip()}%"
        # Matches on the contact's own name/number, OR any message body in the thread -- the
        # message-body branch needs its own correlated EXISTS rather than a JOIN, since a JOIN
        # against conversation_messages would return one row per matching message instead of one
        # per conversation.
        message_match = select(ConversationMessage.id).where(ConversationMessage.conversation_id == Conversation.id, ConversationMessage.body.ilike(like)).exists()
        query = query.join(Contact, Contact.id == Conversation.contact_id).where(or_(Contact.name.ilike(like), Contact.wa_id.ilike(like), message_match))
    query = query.order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc()).limit(limit).offset(offset)
    conversations = db.scalars(query).all()
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_([c.contact_id for c in conversations]))).all()} if conversations else {}
    latest_messages = _latest_messages_for(db, [c.id for c in conversations])
    return [_conversation_out(db, conversation, contacts[conversation.contact_id], latest_messages.get(conversation.id)) for conversation in conversations]


@router.get("/conversations/counts", response_model=ConversationCountsOut)
def get_conversation_counts(status: str | None = None, is_ticket: bool | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """status omitted/empty counts across every status -- must match whatever status filter the
    caller's conversation list is actually showing, or these numbers contradict what's on screen."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    base = select(func.count()).select_from(Conversation).where(Conversation.entity_id == entity.id)
    if status:
        base = base.where(Conversation.status == status)
    if is_ticket is not None:
        base = base.where(Conversation.is_ticket == is_ticket)
    unassigned = db.scalar(base.where(Conversation.assigned_user_id.is_(None))) or 0
    assigned_to_me = db.scalar(base.where(Conversation.assigned_user_id == user.id)) or 0
    all_count = db.scalar(base) or 0
    return ConversationCountsOut(unassigned=unassigned, assigned_to_me=assigned_to_me, all=all_count)


@router.get("/conversations/ticket-counts", response_model=TicketCountsOut)
def get_ticket_counts(channel: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Backs the Tickets list's status rail -- every status's count at once (see TicketCountsOut's
    own docstring for why this is a separate endpoint from /conversations/counts rather than that
    one's status filter just being made optional: the plain WhatsApp inbox's own counts widget
    deliberately still mirrors its active status filter, unrelated behavior this must not change)."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    base = select(func.count()).select_from(Conversation).where(Conversation.entity_id == entity.id, Conversation.is_ticket.is_(True))
    if channel:
        base = base.where(Conversation.channel == channel)
    unassigned = db.scalar(base.where(Conversation.assigned_user_id.is_(None))) or 0
    assigned_to_me = db.scalar(base.where(Conversation.assigned_user_id == user.id)) or 0
    all_count = db.scalar(base) or 0
    open_count = db.scalar(base.where(Conversation.status == "open")) or 0
    pending_count = db.scalar(base.where(Conversation.status == "pending")) or 0
    resolved_count = db.scalar(base.where(Conversation.status == "resolved")) or 0
    return TicketCountsOut(
        unassigned=unassigned, assigned_to_me=assigned_to_me, all=all_count,
        open=open_count, pending=pending_count, resolved=resolved_count,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(conversation_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    messages = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at.asc())).all()
    base = _conversation_out(db, conversation, contact)
    return ConversationDetailOut(**base.model_dump(), messages=[_message_out(m) for m in messages])


def _maybe_send_csat_request(db: Session, entity_id: str, conversation: Conversation, contact: Contact, user_id: str) -> None:
    """Sent as a 1-10-row interactive list (not a 1-3 button message -- Meta caps those at 3
    buttons, too few for a 1-5 scale) with rows titled "1".."5" so the inbound list_reply's own
    title doubles as the rating; waba_webhooks._match_csat_response reads it back that way."""
    settings_row = db.get(CsatSettings, entity_id)
    if not settings_row or not settings_row.enabled or not contact.wa_id:
        return
    sections = [{"title": "Rating", "rows": [{"id": str(n), "title": str(n)} for n in range(1, 6)]}]
    try:
        send_whatsapp_interactive_list(db, entity_id, contact.wa_id, "How would you rate this conversation? (1 = poor, 5 = excellent)", "Rate", sections, sent_by_user_id=user_id)
    except (DomainError, MetaApiError):
        return
    db.add(CsatResponse(conversation_id=conversation.id, entity_id=entity_id))


@router.put("/conversations/{conversation_id}", response_model=ConversationOut)
def update_conversation(conversation_id: str, payload: ConversationUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if payload.status is not None:
        just_resolved = payload.status == "resolved" and conversation.status != "resolved"
        conversation.status = payload.status
        if just_resolved:
            _maybe_send_csat_request(db, entity.id, conversation, contact, user.id)
    # "assigned_user_id": null is a real, meaningful request (unassign) -- checking `is not None`
    # like `status` above would make that indistinguishable from the field being omitted
    # entirely, so this checks whether the client actually sent the field at all instead.
    if "assigned_user_id" in payload.model_fields_set:
        if payload.assigned_user_id is not None:
            assignee = db.get(User, payload.assigned_user_id)
            if not assignee or assignee.organization_id != user.organization_id:
                raise HTTPException(status_code=422, detail="assigned_user_id must belong to your organization")
            if assignee.max_open_conversations is not None and assignee.id != conversation.assigned_user_id:
                open_count = db.scalar(
                    select(func.count()).select_from(Conversation)
                    .where(Conversation.assigned_user_id == assignee.id, Conversation.status != "resolved"),
                ) or 0
                if open_count >= assignee.max_open_conversations:
                    raise HTTPException(status_code=422, detail=f"{assignee.full_name} is at their {assignee.max_open_conversations}-conversation capacity limit")
        conversation.assigned_user_id = payload.assigned_user_id
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


@router.post("/conversations/{conversation_id}/convert-to-ticket", response_model=ConversationOut)
def convert_conversation_to_ticket(conversation_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """One-way -- there's no "convert back", same as invoicing.py never un-numbers an issued
    invoice. Ticket numbers come from a Postgres sequence (mirrors invoicing.py's own
    invoice_number_seq pattern) so they're short, sequential, and human-readable rather than a
    raw UUID; created lazily here (IF NOT EXISTS) since this is the first feature in the
    codebase to need it, and sync_schema.py only manages tables/columns, not sequences."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not channel_active(db, entity.id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to convert conversations to tickets")
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if conversation.is_ticket:
        raise HTTPException(status_code=409, detail="This conversation is already a ticket")
    db.execute(text("CREATE SEQUENCE IF NOT EXISTS ticket_number_seq"))
    seq_val = db.execute(text("SELECT nextval('ticket_number_seq')")).scalar()
    conversation.is_ticket = True
    conversation.ticket_number = f"TKT-{datetime.now(timezone.utc).year}-{seq_val:06d}"
    conversation.ticket_created_at = datetime.now(timezone.utc)
    sla = db.get(SlaPolicy, entity.id)
    if sla and sla.enabled:
        conversation.resolution_due_at = datetime.now(timezone.utc) + timedelta(minutes=sla.resolution_minutes)
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


@router.patch("/conversations/{conversation_id}/priority", response_model=ConversationOut)
def update_ticket_priority(conversation_id: str, payload: TicketPriorityUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    conversation.priority = payload.priority
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


@router.patch("/conversations/{conversation_id}/category", response_model=ConversationOut)
def update_ticket_category(conversation_id: str, payload: TicketCategoryUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    conversation.category = payload.category
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


@router.patch("/conversations/{conversation_id}/group", response_model=ConversationOut)
def update_ticket_group(conversation_id: str, payload: TicketGroupAssignRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if payload.group_id:
        group = db.get(TicketGroup, payload.group_id)
        if not group or group.entity_id != entity.id:
            raise HTTPException(status_code=422, detail="group_id must belong to your organization")
    conversation.group_id = payload.group_id
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


@router.patch("/conversations/{conversation_id}/custom-fields", response_model=ConversationOut)
def update_ticket_custom_fields(conversation_id: str, payload: TicketCustomFieldsUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    conversation.ticket_custom_fields = payload.ticket_custom_fields
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


@router.patch("/conversations/{conversation_id}/subject", response_model=ConversationOut)
def update_conversation_subject(conversation_id: str, payload: ConversationSubjectUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    conversation.subject = payload.subject
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


@router.patch("/conversations/{conversation_id}/cc", response_model=ConversationOut)
def update_conversation_cc(conversation_id: str, payload: ConversationCcUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    conversation.cc_emails = payload.cc_emails
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


# --- Ticket groups (Freshdesk-style team routing) ---------------------------------------------

def _ticket_group_out(group: TicketGroup) -> TicketGroupOut:
    return TicketGroupOut(id=group.id, name=group.name, member_user_ids=group.member_user_ids or [])


@router.get("/ticket-groups", response_model=list[TicketGroupOut])
def list_ticket_groups(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    groups = db.scalars(select(TicketGroup).where(TicketGroup.entity_id == entity.id)).all()
    return [_ticket_group_out(g) for g in groups]


@router.post("/ticket-groups", response_model=TicketGroupOut)
def create_ticket_group(payload: TicketGroupCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    group = TicketGroup(entity_id=entity.id, name=payload.name.strip(), member_user_ids=payload.member_user_ids)
    db.add(group)
    db.commit()
    db.refresh(group)
    return _ticket_group_out(group)


@router.delete("/ticket-groups/{group_id}")
def delete_ticket_group(group_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    group = db.get(TicketGroup, group_id)
    if not group or group.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Ticket group not found")
    db.execute(text("UPDATE conversations SET group_id = NULL WHERE group_id = :gid"), {"gid": group_id})
    db.delete(group)
    db.commit()
    return {"deleted": True}


@router.post("/conversations/{conversation_id}/read", response_model=ConversationOut)
def mark_conversation_as_read(conversation_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Called by the frontend the moment an agent opens a conversation -- stamps last_read_at and
    best-effort sends Meta a read receipt for the latest inbound message (see
    waba_dispatch.mark_conversation_read for why a Meta-side failure never blocks this)."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    connection = db.get(WabaConnection, entity.id)
    if connection:
        mark_conversation_read(db, conversation, connection)
        db.commit()
    return _conversation_out(db, conversation, contact)


@router.get("/assignable-users", response_model=list[AssignableUserOut])
def list_assignable_users(user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not user.organization_id:
        return []
    members = db.scalars(select(User).where(User.organization_id == user.organization_id).order_by(User.created_at.asc())).all()
    return [AssignableUserOut(id=m.id, full_name=m.full_name, email=m.email) for m in members]


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageOut)
def send_conversation_message(conversation_id: str, payload: ConversationMessageCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)

    if payload.is_private:
        # An internal note never touches Meta -- no wamid, no send. Same conversation thread as
        # real messages (every competitor platform researched keeps notes inline, not a separate
        # view) so an agent picking up the thread sees the note with full surrounding context.
        message = ConversationMessage(conversation_id=conversation.id, direction="outbound", is_private=True, message_type="text", body=payload.body, sent_by_user_id=user.id)
        db.add(message)
        db.commit()
        db.refresh(message)
        publish_event(entity.id, {"type": "message", "message": message_payload(message)})
        return _message_out(message)

    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    try:
        message = send_whatsapp_text(db, entity.id, contact.wa_id, payload.body, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this message: {exc}") from exc
    return _message_out(message)


@router.post("/conversations/{conversation_id}/media", response_model=ConversationMessageOut)
async def send_conversation_media(conversation_id: str, file: UploadFile = File(...), caption: str | None = Form(default=None), user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")

    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0]
    message_type = waba_media.message_type_for_mime(mime_type or "")
    if not message_type:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{mime_type}' for WhatsApp media")
    content = await file.read()
    try:
        message = send_whatsapp_media(db, entity.id, contact.wa_id, content, file.filename or "upload", mime_type, message_type, caption, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this file: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _message_out(message)


@router.post("/conversations/{conversation_id}/location-message", response_model=ConversationMessageOut)
def send_conversation_location(conversation_id: str, payload: LocationMessageRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    try:
        message = send_whatsapp_location(db, entity.id, contact.wa_id, payload.latitude, payload.longitude, payload.name, payload.address, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this location: {exc}") from exc
    return _message_out(message)


@router.post("/conversations/{conversation_id}/contact-message", response_model=ConversationMessageOut)
def send_conversation_contact(conversation_id: str, payload: ContactMessageRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    meta_contacts = [{"name": {"formatted_name": c.formatted_name, "first_name": c.formatted_name}, "phones": [{"phone": c.phone}]} for c in payload.contacts]
    try:
        message = send_whatsapp_contact(db, entity.id, contact.wa_id, meta_contacts, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this contact: {exc}") from exc
    return _message_out(message)


@router.post("/conversations/{conversation_id}/interactive-buttons", response_model=ConversationMessageOut)
def send_conversation_interactive_buttons(conversation_id: str, payload: InteractiveButtonRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    buttons = [{"id": f"btn_{i}", "title": label} for i, label in enumerate(payload.button_labels)]
    try:
        message = send_whatsapp_interactive_buttons(db, entity.id, contact.wa_id, payload.body_text, buttons, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send these buttons: {exc}") from exc
    return _message_out(message)


@router.post("/conversations/{conversation_id}/interactive-list", response_model=ConversationMessageOut)
def send_conversation_interactive_list(conversation_id: str, payload: InteractiveListRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    rows = [{"id": f"row_{i}", "title": r.title, "description": r.description} for i, r in enumerate(payload.rows)]
    sections = [{"title": "Options", "rows": rows}]
    try:
        message = send_whatsapp_interactive_list(db, entity.id, contact.wa_id, payload.body_text, payload.button_label, sections, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this list: {exc}") from exc
    return _message_out(message)


@router.post("/conversations/{conversation_id}/product", response_model=ConversationMessageOut)
def send_conversation_product(conversation_id: str, payload: ProductMessageRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    try:
        message = send_whatsapp_product(db, entity.id, contact.wa_id, payload.product_retailer_id, payload.body_text, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this product: {exc}") from exc
    return _message_out(message)


@router.post("/conversations/{conversation_id}/react", response_model=ConversationMessageOut)
def react_to_message(conversation_id: str, payload: ReactionRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    reacted_to = db.get(ConversationMessage, payload.message_id)
    if not reacted_to or reacted_to.conversation_id != conversation.id or not reacted_to.meta_message_id:
        raise HTTPException(status_code=404, detail="Message not found in this conversation")
    try:
        message = send_whatsapp_reaction(db, entity.id, contact.wa_id, reacted_to.meta_message_id, payload.emoji, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this reaction: {exc}") from exc
    return _message_out(message)


@router.get("/media/{message_id}")
def get_conversation_media(message_id: str, token: str, db: Session = Depends(get_db)):
    """Serves a previously stored WhatsApp media file (inbound-downloaded or outbound-sent copy)
    back to the browser. Authenticated via a token query param, not the usual Authorization
    header -- an <img>/<video> tag can't attach custom headers, same reasoning and convention as
    the /v1/waba/ws WebSocket."""
    user = authenticate_query_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    message = db.get(ConversationMessage, message_id)
    if not message or not message.media_url:
        raise HTTPException(status_code=404, detail="Media not found")
    conversation = db.get(Conversation, message.conversation_id)
    if not conversation or conversation.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Media not found")
    try:
        content = waba_media.read_media(message.media_url)
    except OSError:
        raise HTTPException(status_code=404, detail="Media file is no longer available")
    mime_type = mimetypes.guess_type(message.media_url)[0] or "application/octet-stream"
    return Response(content=content, media_type=mime_type)


# --- Templates ----------------------------------------------------------------------------------

@router.get("/templates", response_model=list[WabaTemplateOut])
def list_templates(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Fetched live from Meta on every call rather than cached -- template approval status can
    change on Meta's side at any time, and the composer needs the current status, not a possibly
    stale snapshot. Only APPROVED templates are usable for a real send; others are still returned
    so the UI can show "pending review" rather than silently hiding them."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        return []
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        templates = list_message_templates(connection.waba_id, access_token)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not load templates from Meta: {exc}") from exc
    out = []
    for t in templates:
        components = t.get("components", [])
        body_component = next((c for c in components if c.get("type") == "BODY"), None)
        header_component = next((c for c in components if c.get("type") == "HEADER"), None)
        footer_component = next((c for c in components if c.get("type") == "FOOTER"), None)
        buttons_component = next((c for c in components if c.get("type") == "BUTTONS"), None)
        header_format = header_component.get("format", "TEXT") if header_component else "TEXT"
        out.append(WabaTemplateOut(
            id=t.get("id"), name=t["name"], status=t.get("status", "UNKNOWN"), language=t.get("language", ""), category=t.get("category", ""),
            header_text=header_component.get("text") if header_component and header_format == "TEXT" else None,
            header_format=header_format,
            body=body_component.get("text") if body_component else None,
            footer_text=footer_component.get("text") if footer_component else None,
            buttons=[
                TemplateButtonOut(type=b.get("type", ""), text=b.get("text", ""), url=b.get("url"), phone_number=b.get("phone_number"))
                for b in (buttons_component.get("buttons", []) if buttons_component else [])
            ],
        ))
    return out


@router.post("/conversations/{conversation_id}/template-message", response_model=ConversationMessageOut)
def send_conversation_template(conversation_id: str, payload: TemplateMessageRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The only way to (re)start a conversation once Meta's 24-hour free-form window has closed --
    see waba_meta.send_template_message's own docstring."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    try:
        message = send_whatsapp_template(db, entity.id, contact.wa_id, payload.template_name, payload.language_code, payload.body_params, payload.preview_body, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this template: {exc}") from exc
    return _message_out(message)


@router.post("/conversations/start", response_model=ConversationOut)
def start_conversation(payload: StartConversationRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Kicks off a brand-new conversation to a number that's never messaged in -- the inbox's
    "Reply" box only ever works inside an existing conversation, since there's nowhere to type a
    destination number; this is the counterpart for starting one. send_whatsapp_template's own
    _resolve_send_target already finds-or-creates the Contact/Conversation for a wa_id it's never
    seen, so this just normalizes the number, optionally names the contact, and sends."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    wa_id = "".join(ch for ch in payload.wa_id if ch.isdigit())
    if not wa_id:
        raise HTTPException(status_code=422, detail="Enter a valid WhatsApp number")
    try:
        message = send_whatsapp_template(db, entity.id, wa_id, payload.template_name, payload.language_code, payload.body_params, payload.preview_body, sent_by_user_id=user.id)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this template: {exc}") from exc
    conversation = db.get(Conversation, message.conversation_id)
    contact = db.get(Contact, conversation.contact_id)
    if payload.name and not contact.name:
        contact.name = payload.name
        db.commit()
    return _conversation_out(db, conversation, contact, message)


def _validate_template_buttons(buttons: list) -> None:
    """Mirrors Meta's own button rules (Message Templates docs): quick-reply buttons can't be
    mixed with call-to-action buttons (URL/phone) in the same template, and each type has its own
    per-template cap."""
    if len(buttons) > 10:
        raise HTTPException(status_code=422, detail="A template can have at most 10 buttons")
    quick_replies = [b for b in buttons if b.type == "QUICK_REPLY"]
    urls = [b for b in buttons if b.type == "URL"]
    phones = [b for b in buttons if b.type == "PHONE_NUMBER"]
    if quick_replies and (urls or phones):
        raise HTTPException(status_code=422, detail="Quick-reply buttons can't be mixed with URL or phone-number buttons")
    if len(urls) > 2:
        raise HTTPException(status_code=422, detail="A template can have at most 2 URL buttons")
    if len(phones) > 1:
        raise HTTPException(status_code=422, detail="A template can have at most 1 phone-number button")
    for b in urls:
        if not b.url:
            raise HTTPException(status_code=422, detail="A URL button needs a url")
    for b in phones:
        if not b.phone_number:
            raise HTTPException(status_code=422, detail="A phone-number button needs a phone_number")


@router.post("/templates/header-media")
def upload_template_header(file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Returns a header_handle for TemplateCreateRequest.header_handle -- a separate call from
    template creation itself since Meta's Resumable Upload API is a genuinely different flow
    (uploads under the app, not the WABA/phone number) from create_template's plain JSON body."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number before creating templates")
    app_id, _config_id, _app_secret = get_platform_waba_settings(db)
    if not app_id:
        raise HTTPException(status_code=422, detail="WhatsApp is not fully configured on this platform yet")
    access_token = decrypt_secret(connection.access_token_encrypted)
    content = file.file.read()
    try:
        handle = upload_template_header_media(app_id, access_token, content, file.content_type or "application/octet-stream")
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not upload this file to Meta: {exc}") from exc
    return {"header_handle": handle}


@router.post("/templates", response_model=WabaTemplateOut)
def create_template(payload: TemplateCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Submits a new template for Meta's review -- it comes back PENDING, not immediately
    sendable. GET /templates (list_templates above) is how the caller later sees it move to
    APPROVED or REJECTED; there's no separate "check my submission" endpoint."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number before creating templates")
    if payload.header_format != "TEXT" and not payload.header_handle:
        raise HTTPException(status_code=422, detail="Upload the header media first (POST /templates/header-media) before submitting a media-header template")
    _validate_template_buttons(payload.buttons)
    access_token = decrypt_secret(connection.access_token_encrypted)
    buttons_payload = [{"type": b.type, "text": b.text, **({"url": b.url} if b.type == "URL" else {}), **({"phone_number": b.phone_number} if b.type == "PHONE_NUMBER" else {})} for b in payload.buttons]
    try:
        create_message_template(
            connection.waba_id, access_token, payload.name, payload.category, payload.language, payload.body_text,
            payload.example_params or None, header_text=payload.header_text, header_format=payload.header_format,
            header_handle=payload.header_handle, footer_text=payload.footer_text, buttons=buttons_payload or None,
        )
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not submit this template: {exc}") from exc
    return WabaTemplateOut(
        name=payload.name, status="PENDING", language=payload.language, category=payload.category,
        header_text=payload.header_text, header_format=payload.header_format, body=payload.body_text, footer_text=payload.footer_text,
        buttons=[TemplateButtonOut(type=b.type, text=b.text, url=b.url, phone_number=b.phone_number) for b in payload.buttons],
    )


@router.delete("/templates/{template_name}")
def delete_template(template_name: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number before managing templates")
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        delete_message_template(connection.waba_id, access_token, template_name)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not delete this template: {exc}") from exc
    return {"deleted": True}


# --- Contacts ---------------------------------------------------------------------------------

@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(search: str | None = None, label_id: str | None = None, limit: int = 50, offset: int = 0, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    limit = max(1, min(limit, 200))
    query = select(Contact).where(Contact.entity_id == entity.id)
    if search:
        like = f"%{search.strip()}%"
        query = query.where((Contact.name.ilike(like)) | (Contact.wa_id.ilike(like)) | (Contact.email.ilike(like)))
    if label_id:
        query = query.join(ContactLabel, ContactLabel.contact_id == Contact.id).where(ContactLabel.label_id == label_id)
    query = query.order_by(Contact.created_at.desc()).limit(limit).offset(offset)
    contacts = db.scalars(query).all()
    return [_contact_out(db, contact) for contact in contacts]


# CSV export/import registered before the /contacts/{contact_id} routes below -- FastAPI/
# Starlette matches routes in registration order, so "/contacts/export" would otherwise be
# swallowed by "/contacts/{contact_id}" (matching contact_id="export") if it came after.
@router.get("/contacts/export")
def export_contacts(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    contacts = db.scalars(select(Contact).where(Contact.entity_id == entity.id).order_by(Contact.created_at)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "wa_id", "email", "opted_out"])
    for c in contacts:
        writer.writerow([c.name or "", c.wa_id or "", c.email or "", "yes" if c.opted_out else "no"])
    return Response(content=buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=contacts.csv"})


@router.post("/contacts/import")
def import_contacts(file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None or "wa_id" not in {f.strip().lower() for f in reader.fieldnames}:
        raise HTTPException(status_code=422, detail="CSV must have a 'wa_id' column (name and email are optional)")
    created, updated, skipped = 0, 0, 0
    for row in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        wa_id = row.get("wa_id")
        if not wa_id:
            skipped += 1
            continue
        contact = db.scalar(select(Contact).where(Contact.entity_id == entity.id, Contact.wa_id == wa_id))
        if contact:
            if row.get("name"):
                contact.name = row["name"]
            if row.get("email"):
                contact.email = row["email"]
            updated += 1
        else:
            db.add(Contact(entity_id=entity.id, wa_id=wa_id, name=row.get("name") or None, email=row.get("email") or None))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


@router.get("/contacts/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return _contact_out(db, contact)


@router.put("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: str, payload: ContactUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    if payload.name is not None:
        contact.name = payload.name
    if payload.custom_attributes is not None:
        contact.custom_attributes = payload.custom_attributes
    if payload.opted_out is not None:
        contact.opted_out = payload.opted_out
    db.commit()
    db.refresh(contact)
    return _contact_out(db, contact)


@router.get("/contacts-directory", response_model=list[ContactDirectoryEntryOut])
def list_contacts_directory(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """One row per WhatsApp contact -- last message/reply time, ticket status, and whether
    they're already linked to a CRM lead/customer. Not CRM-gated itself (it's just contact/
    conversation data any WhatsApp-active entity already has) -- only the conversion actions
    reachable from a contact's detail view require the CRM channel."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    contacts = db.scalars(select(Contact).where(Contact.entity_id == entity.id).order_by(Contact.created_at.desc())).all()
    if not contacts:
        return []
    contact_ids = [c.id for c in contacts]
    conversations = {c.contact_id: c for c in db.scalars(select(Conversation).where(Conversation.contact_id.in_(contact_ids))).all()}
    conversation_ids = [c.id for c in conversations.values()]
    last_replies: dict[str, datetime] = {}
    if conversation_ids:
        rows = db.execute(
            select(ConversationMessage.conversation_id, func.max(ConversationMessage.created_at))
            .where(ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.direction == "outbound", ConversationMessage.is_private.is_(False))
            .group_by(ConversationMessage.conversation_id),
        ).all()
        last_replies = dict(rows)
    # Lead.contact_id points at a CrmContact now, not this WABA Contact directly -- resolve
    # through each contact's own crm_contact_id link (set at conversion time) to find its lead.
    crm_contact_ids = [c.crm_contact_id for c in contacts if c.crm_contact_id]
    leads_by_crm_contact_id = {
        lead.contact_id: lead for lead in db.scalars(select(Lead).where(Lead.contact_id.in_(crm_contact_ids))).all()
    } if crm_contact_ids else {}

    out = []
    for contact in contacts:
        conversation = conversations.get(contact.id)
        lead = leads_by_crm_contact_id.get(contact.crm_contact_id) if contact.crm_contact_id else None
        out.append(ContactDirectoryEntryOut(
            contact=_contact_out(db, contact),
            conversation_id=conversation.id if conversation else None,
            last_message_at=conversation.last_message_at.isoformat() if conversation and conversation.last_message_at else None,
            last_reply_at=last_replies[conversation.id].isoformat() if conversation and conversation.id in last_replies else None,
            is_ticket=bool(conversation and conversation.is_ticket),
            ticket_number=conversation.ticket_number if conversation else None,
            ticket_status=conversation.status if conversation and conversation.is_ticket else None,
            lead_id=lead.id if lead else None,
            customer_id=contact.customer_id,
        ))
    return out


@router.get("/contacts/{contact_id}/timeline", response_model=ContactTimelineOut)
def get_contact_timeline(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Full chat trail for one contact plus their CRM link status -- the detail view reachable
    from the contacts directory's "View" action."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    conversation = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id))
    messages = []
    if conversation:
        messages = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.created_at.asc())).all()

    # CRM data now lives on a separate CrmContact (see Contact.crm_contact_id) -- a WABA contact
    # that's never been converted has no linked CrmContact at all, so lead/deals/customer all
    # stay empty until an agent explicitly converts it.
    crm_contact = db.get(CrmContact, contact.crm_contact_id) if contact.crm_contact_id else None
    lead_out = None
    deals_out: list[DealOut] = []
    customer_out = None
    if crm_contact:
        crm_contact_out = _crm_contact_out(crm_contact)
        # Most recent open (or, absent that, most recent overall) thin Lead -- a contact can have
        # at most one useful "current" Lead at a time even though the row isn't unique-constrained.
        lead = db.scalar(select(Lead).where(Lead.contact_id == crm_contact.id, Lead.entity_id == entity.id).order_by(Lead.created_at.desc()))
        deals = db.scalars(select(Deal).where(Deal.contact_id == crm_contact.id, Deal.entity_id == entity.id).order_by(Deal.created_at.desc())).all()
        customer = db.get(Customer, contact.customer_id) if contact.customer_id else None
        lead_out = LeadOut(
            id=lead.id, contact=crm_contact_out, company_name=lead.company_name, source=lead.source, status=lead.status,
            owner_user_id=lead.owner_user_id, notes=lead.notes, custom_fields=lead.custom_fields or {}, score=lead.score,
            converted_at=lead.converted_at.isoformat() if lead.converted_at else None, converted_deal_id=lead.converted_deal_id,
            created_at=lead.created_at.isoformat(),
        ) if lead else None
        deals_out = [
            DealOut(
                id=deal.id, contact=crm_contact_out, pipeline_id=deal.pipeline_id, stage=deal.stage, source=deal.source,
                converted_from_conversation_id=deal.converted_from_conversation_id, converted_from_lead_id=deal.converted_from_lead_id,
                owner_user_id=deal.owner_user_id, notes=deal.notes, value=float(deal.value) if deal.value is not None else None,
                probability=deal.probability, expected_close_date=deal.expected_close_date.isoformat() if deal.expected_close_date else None,
                status=deal.status, lost_reason=deal.lost_reason, custom_fields=deal.custom_fields or {},
                created_at=deal.created_at.isoformat(),
            ) for deal in deals
        ]
        customer_out = CustomerOut(
            id=customer.id, contact=crm_contact_out, deal_id=customer.deal_id,
            converted_from_conversation_id=customer.converted_from_conversation_id, owner_user_id=customer.owner_user_id,
            notes=customer.notes, custom_fields=customer.custom_fields or {}, created_at=customer.created_at.isoformat(),
        ) if customer else None

    open_tickets = 1 if conversation and conversation.is_ticket and conversation.status != "resolved" else 0
    resolved_tickets = 1 if conversation and conversation.is_ticket and conversation.status == "resolved" else 0

    return ContactTimelineOut(
        contact=_contact_out(db, contact), conversation_id=conversation.id if conversation else None,
        crm_contact_id=contact.crm_contact_id,
        lead=lead_out, deals=deals_out, customer=customer_out, tickets=TicketSummary(open=open_tickets, resolved=resolved_tickets),
        messages=[_message_out(m) for m in messages],
    )


# --- Labels -----------------------------------------------------------------------------------

@router.get("/labels", response_model=list[LabelOut])
def list_labels(scope: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    query = select(Label).where(Label.entity_id == entity.id)
    if scope:
        query = query.where(Label.scope == scope)
    labels = db.scalars(query.order_by(Label.name.asc())).all()
    return [LabelOut(id=label.id, scope=label.scope, name=label.name, color=label.color) for label in labels]


@router.post("/labels", response_model=LabelOut)
def create_label(payload: LabelCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    label = Label(entity_id=entity.id, scope=payload.scope, name=payload.name.strip(), color=payload.color)
    db.add(label)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A {payload.scope} label named '{payload.name}' already exists")
    db.refresh(label)
    return LabelOut(id=label.id, scope=label.scope, name=label.name, color=label.color)


@router.delete("/labels/{label_id}")
def delete_label(label_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    label = _get_owned_label(db, entity.id, label_id)
    db.delete(label)
    db.commit()
    return {"deleted": True}


@router.post("/conversations/{conversation_id}/labels/{label_id}", response_model=ConversationOut)
def attach_conversation_label(conversation_id: str, label_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    label = _get_owned_label(db, entity.id, label_id)
    if label.scope != "conversation":
        raise HTTPException(status_code=422, detail="This label is not a conversation label")
    if not db.get(ConversationLabel, (conversation.id, label.id)):
        db.add(ConversationLabel(conversation_id=conversation.id, label_id=label.id))
        db.commit()
    return _conversation_out(db, conversation, contact)


@router.delete("/conversations/{conversation_id}/labels/{label_id}", response_model=ConversationOut)
def detach_conversation_label(conversation_id: str, label_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    link = db.get(ConversationLabel, (conversation.id, label_id))
    if link:
        db.delete(link)
        db.commit()
    return _conversation_out(db, conversation, contact)


@router.post("/contacts/{contact_id}/labels/{label_id}", response_model=ContactOut)
def attach_contact_label(contact_id: str, label_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    label = _get_owned_label(db, entity.id, label_id)
    if label.scope != "contact":
        raise HTTPException(status_code=422, detail="This label is not a contact label")
    if not db.get(ContactLabel, (contact.id, label.id)):
        db.add(ContactLabel(contact_id=contact.id, label_id=label.id))
        db.commit()
    return _contact_out(db, contact)


@router.delete("/contacts/{contact_id}/labels/{label_id}", response_model=ContactOut)
def detach_contact_label(contact_id: str, label_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    link = db.get(ContactLabel, (contact_id, label_id))
    if link:
        db.delete(link)
        db.commit()
    return _contact_out(db, contact)


# --- Canned responses ---------------------------------------------------------------------------

@router.get("/canned-responses", response_model=list[CannedResponseOut])
def list_canned_responses(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = db.scalars(select(CannedResponse).where(CannedResponse.entity_id == entity.id).order_by(CannedResponse.shortcut.asc())).all()
    return [CannedResponseOut(id=item.id, shortcut=item.shortcut, body=item.body) for item in items]


@router.post("/canned-responses", response_model=CannedResponseOut)
def create_canned_response(payload: CannedResponseCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item = CannedResponse(entity_id=entity.id, shortcut=payload.shortcut.strip().lstrip("/"), body=payload.body)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A canned response with shortcut '/{payload.shortcut.strip().lstrip('/')}' already exists")
    db.refresh(item)
    return CannedResponseOut(id=item.id, shortcut=item.shortcut, body=item.body)


@router.put("/canned-responses/{canned_response_id}", response_model=CannedResponseOut)
def update_canned_response(canned_response_id: str, payload: CannedResponseCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item = db.get(CannedResponse, canned_response_id)
    if not item or item.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Canned response not found")
    item.shortcut = payload.shortcut.strip().lstrip("/")
    item.body = payload.body
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A canned response with shortcut '/{item.shortcut}' already exists")
    db.refresh(item)
    return CannedResponseOut(id=item.id, shortcut=item.shortcut, body=item.body)


@router.delete("/canned-responses/{canned_response_id}")
def delete_canned_response(canned_response_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item = db.get(CannedResponse, canned_response_id)
    if not item or item.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Canned response not found")
    db.delete(item)
    db.commit()
    return {"deleted": True}


# --- Automation rules ---------------------------------------------------------------------------

def _rule_out(rule: AutomationRule) -> AutomationRuleOut:
    return AutomationRuleOut(id=rule.id, name=rule.name, trigger_type=rule.trigger_type, trigger_value=rule.trigger_value, action_type=rule.action_type, action_value=rule.action_value, active=rule.active, priority=rule.priority)


@router.get("/automation-rules", response_model=list[AutomationRuleOut])
def list_automation_rules(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rules = db.scalars(select(AutomationRule).where(AutomationRule.entity_id == entity.id).order_by(AutomationRule.priority.asc())).all()
    return [_rule_out(r) for r in rules]


@router.post("/automation-rules", response_model=AutomationRuleOut)
def create_automation_rule(payload: AutomationRuleCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.trigger_type == "keyword" and not payload.trigger_value:
        raise HTTPException(status_code=422, detail="A keyword trigger needs a keyword to match")
    if payload.action_type == "assign" and not db.get(User, payload.action_value):
        raise HTTPException(status_code=422, detail="action_value must be a valid user id for an assign action")
    if payload.action_type == "reply" and not db.get(CannedResponse, payload.action_value):
        raise HTTPException(status_code=422, detail="action_value must be a valid canned response id for a reply action")
    if payload.action_type == "label":
        label = db.get(Label, payload.action_value)
        if not label or label.entity_id != entity.id or label.scope != "conversation":
            raise HTTPException(status_code=422, detail="action_value must be a valid conversation label id for a label action")
    rule = AutomationRule(
        entity_id=entity.id, name=payload.name, trigger_type=payload.trigger_type, trigger_value=payload.trigger_value,
        action_type=payload.action_type, action_value=payload.action_value, active=payload.active, priority=payload.priority,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.put("/automation-rules/{rule_id}", response_model=AutomationRuleOut)
def update_automation_rule(rule_id: str, payload: AutomationRuleCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rule = db.get(AutomationRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Automation rule not found")
    rule.name = payload.name
    rule.trigger_type = payload.trigger_type
    rule.trigger_value = payload.trigger_value
    rule.action_type = payload.action_type
    rule.action_value = payload.action_value
    rule.active = payload.active
    rule.priority = payload.priority
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.delete("/automation-rules/{rule_id}")
def delete_automation_rule(rule_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rule = db.get(AutomationRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Automation rule not found")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


# --- Segments -----------------------------------------------------------------------------------

def segment_matching_contacts(db: Session, entity_id: str, segment: Segment) -> list[Contact]:
    """AND semantics across both dimensions -- see Segment's own docstring in models.py. Filters
    in Python rather than a JSON-containment SQL query, matching this codebase's existing
    contacts-directory aggregation approach; fine at the per-entity contact-list scale this
    targets (campaign audiences, not a general-purpose analytics query)."""
    contacts = db.scalars(select(Contact).where(Contact.entity_id == entity_id)).all()
    if segment.label_ids:
        rows = db.execute(select(ContactLabel.contact_id, ContactLabel.label_id).where(ContactLabel.contact_id.in_([c.id for c in contacts]))).all()
        labels_by_contact: dict[str, set] = {}
        for contact_id, label_id in rows:
            labels_by_contact.setdefault(contact_id, set()).add(label_id)
        required = set(segment.label_ids)
        contacts = [c for c in contacts if required.issubset(labels_by_contact.get(c.id, set()))]
    if segment.custom_attributes:
        contacts = [c for c in contacts if all(str((c.custom_attributes or {}).get(k)) == str(v) for k, v in segment.custom_attributes.items())]
    return contacts


def _segment_out(db: Session, segment: Segment) -> SegmentOut:
    return SegmentOut(
        id=segment.id, name=segment.name, label_ids=segment.label_ids, custom_attributes=segment.custom_attributes,
        contact_count=len(segment_matching_contacts(db, segment.entity_id, segment)), created_at=segment.created_at.isoformat(),
    )


@router.get("/segments", response_model=list[SegmentOut])
def list_segments(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    segments = db.scalars(select(Segment).where(Segment.entity_id == entity.id).order_by(Segment.created_at.desc())).all()
    return [_segment_out(db, s) for s in segments]


@router.post("/segments", response_model=SegmentOut)
def create_segment(payload: SegmentCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    segment = Segment(entity_id=entity.id, name=payload.name.strip(), label_ids=payload.label_ids, custom_attributes=payload.custom_attributes)
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return _segment_out(db, segment)


@router.get("/segments/{segment_id}/contacts", response_model=list[ContactOut])
def list_segment_contacts(segment_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    segment = db.get(Segment, segment_id)
    if not segment or segment.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Segment not found")
    return [_contact_out(db, c) for c in segment_matching_contacts(db, entity.id, segment)]


@router.delete("/segments/{segment_id}")
def delete_segment(segment_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    segment = db.get(Segment, segment_id)
    if not segment or segment.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Segment not found")
    db.delete(segment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This segment is used by one or more campaigns -- delete those campaigns first")
    return {"deleted": True}


# --- Macros ---------------------------------------------------------------------------------

def _macro_out(macro: Macro) -> MacroOut:
    return MacroOut(id=macro.id, name=macro.name, actions=macro.actions, created_at=macro.created_at.isoformat())


@router.get("/macros", response_model=list[MacroOut])
def list_macros(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    macros = db.scalars(select(Macro).where(Macro.entity_id == entity.id).order_by(Macro.name)).all()
    return [_macro_out(m) for m in macros]


@router.post("/macros", response_model=MacroOut)
def create_macro(payload: MacroCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    macro = Macro(entity_id=entity.id, name=payload.name.strip(), actions=[a.model_dump() for a in payload.actions])
    db.add(macro)
    db.commit()
    db.refresh(macro)
    return _macro_out(macro)


@router.delete("/macros/{macro_id}")
def delete_macro(macro_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    macro = db.get(Macro, macro_id)
    if not macro or macro.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Macro not found")
    db.delete(macro)
    db.commit()
    return {"deleted": True}


@router.post("/conversations/{conversation_id}/run-macro/{macro_id}", response_model=ConversationOut)
def run_macro(conversation_id: str, macro_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    macro = db.get(Macro, macro_id)
    if not macro or macro.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Macro not found")
    for action in macro.actions:
        action_type, value = action.get("type"), action.get("value")
        if action_type == "reply" and value:
            canned = db.get(CannedResponse, value)
            if canned and contact.wa_id:
                try:
                    send_whatsapp_text(db, entity.id, contact.wa_id, canned.body, sent_by_user_id=user.id)
                except (DomainError, MetaApiError):
                    pass
        elif action_type == "label" and value:
            if not db.scalar(select(ConversationLabel).where(ConversationLabel.conversation_id == conversation.id, ConversationLabel.label_id == value)):
                db.add(ConversationLabel(conversation_id=conversation.id, label_id=value))
        elif action_type == "status" and value in ("open", "pending", "resolved"):
            conversation.status = value
        elif action_type == "assign":
            conversation.assigned_user_id = value or None
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation, contact)


# --- Business hours -------------------------------------------------------------------------

def _business_hours_out(row: BusinessHours | None) -> BusinessHoursOut:
    if not row:
        return BusinessHoursOut(enabled=False, timezone="Asia/Kolkata", schedule={}, outside_hours_message=None)
    return BusinessHoursOut(enabled=row.enabled, timezone=row.timezone, schedule=row.schedule, outside_hours_message=row.outside_hours_message)


@router.get("/business-hours", response_model=BusinessHoursOut)
def get_business_hours(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _business_hours_out(db.get(BusinessHours, entity.id))


@router.put("/business-hours", response_model=BusinessHoursOut)
def update_business_hours(payload: BusinessHoursUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.get(BusinessHours, entity.id)
    if not row:
        row = BusinessHours(entity_id=entity.id)
        db.add(row)
    row.enabled = payload.enabled
    row.timezone = payload.timezone
    row.schedule = {day: hours.model_dump() for day, hours in payload.schedule.items()}
    row.outside_hours_message = payload.outside_hours_message
    db.commit()
    db.refresh(row)
    return _business_hours_out(row)


# --- SLA -------------------------------------------------------------------------------------

def _sla_policy_out(row: SlaPolicy | None) -> SlaPolicyOut:
    if not row:
        return SlaPolicyOut(enabled=False, first_response_minutes=60, resolution_minutes=480)
    return SlaPolicyOut(enabled=row.enabled, first_response_minutes=row.first_response_minutes, resolution_minutes=row.resolution_minutes)


@router.get("/sla-policy", response_model=SlaPolicyOut)
def get_sla_policy(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _sla_policy_out(db.get(SlaPolicy, entity.id))


@router.put("/sla-policy", response_model=SlaPolicyOut)
def update_sla_policy(payload: SlaPolicyUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.get(SlaPolicy, entity.id)
    if not row:
        row = SlaPolicy(entity_id=entity.id)
        db.add(row)
    row.enabled = payload.enabled
    row.first_response_minutes = payload.first_response_minutes
    row.resolution_minutes = payload.resolution_minutes
    db.commit()
    db.refresh(row)
    return _sla_policy_out(row)


@router.put("/assignable-users/{user_id}/capacity", response_model=AssignableUserOut)
def update_agent_capacity(user_id: str, payload: AgentCapacityUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not user.organization_id:
        raise HTTPException(status_code=422, detail="Complete organisation onboarding before setting agent capacity")
    target = db.get(User, user_id)
    if not target or target.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Teammate not found")
    target.max_open_conversations = payload.max_open_conversations
    db.commit()
    return AssignableUserOut(id=target.id, full_name=target.full_name, email=target.email)


# --- CSAT -----------------------------------------------------------------------------------

@router.get("/csat-settings", response_model=CsatSettingsOut)
def get_csat_settings(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.get(CsatSettings, entity.id)
    return CsatSettingsOut(enabled=bool(row and row.enabled))


@router.put("/csat-settings", response_model=CsatSettingsOut)
def update_csat_settings(payload: CsatSettingsUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.get(CsatSettings, entity.id)
    if not row:
        row = CsatSettings(entity_id=entity.id)
        db.add(row)
    row.enabled = payload.enabled
    db.commit()
    return CsatSettingsOut(enabled=row.enabled)


# --- Outbound webhooks ------------------------------------------------------------------------

@router.get("/webhook-subscription", response_model=WabaWebhookSubscriptionOut)
def get_webhook_subscription(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.get(WabaWebhookSubscription, entity.id)
    if not row:
        return WabaWebhookSubscriptionOut(url=None, enabled=False, secret=None)
    return WabaWebhookSubscriptionOut(url=row.url, enabled=row.enabled, secret=row.secret)


@router.put("/webhook-subscription", response_model=WabaWebhookSubscriptionOut)
def update_webhook_subscription(payload: WabaWebhookSubscriptionUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.get(WabaWebhookSubscription, entity.id)
    if not row:
        row = WabaWebhookSubscription(entity_id=entity.id, secret=secrets.token_hex(32))
        db.add(row)
    row.url = payload.url
    row.enabled = payload.enabled
    db.commit()
    db.refresh(row)
    return WabaWebhookSubscriptionOut(url=row.url, enabled=row.enabled, secret=row.secret)


