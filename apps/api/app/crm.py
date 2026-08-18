"""CRM -- the 3rd channel alongside SMS and WhatsApp, gated by channel_active(db, entity_id,
"crm"). Owns its own CrmContact, genuinely separate from the WhatsApp-owned Contact -- the two
are bridged only by an explicit "convert" action (Contact.crm_contact_id), never a shared row,
per the user's explicit "whatsapp have own and crm have own... if from whatsapp we convert in
crm" decision. Deliberately its own module, never importing from or importing into
dispatch.py/providers.py/webhooks.py (SMS) or waba_dispatch.py/waba_meta.py/waba_webhooks.py
(WhatsApp's own send/receive pipeline) -- same isolation principle as every other channel module.
It's fine (and intentional) for this module to read the shared Conversation/Contact inbox tables
directly, since those were designed from the start as the shared-inbox layer, not WhatsApp-
pipeline internals."""
import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_user
from .crm_quotes import _quote_out
from .crm_sequences import apply_lead_routing
from .database import SessionLocal, get_db
from .email_service import render_email, send_email
from .models import (
    Attachment, Company, Contact, Conversation, ConversationMessage, CrmContact, CrmSettings, CustomFieldDefinition,
    Customer, Deal, DealStageEvent, DEFAULT_CRM_PIPELINE_STAGES, Lead, Notification, Pipeline, Quote, SalesTarget, SavedReport, SavedView, ScoringRule,
    Task, Territory, User, UserRole, WebForm,
)
from .schemas import (
    ActivityMessageOut, AttachmentOut, CompanyCreateRequest, CompanyDetailOut, CompanyOut, CompanySummary, ConsentUpdateRequest, ContactOut,
    CrmContactCreateRequest, CrmContactDetailOut, CrmContactOut, CrmContactUpdateRequest, CrmExtendedReportsOut,
    CrmReportsOut, CrmFunnelStage, CrmSettingsOut, CrmSettingsUpdateRequest, CustomerCreateFromConversationRequest,
    CustomerCreateRequest, CustomerDetailOut, CustomerOut, CustomerUpdateRequest, CustomFieldDefinitionCreateRequest, CustomFieldDefinitionOut,
    DealBulkDeleteRequest, DealBulkOwnerRequest, DealCreateFromConversationRequest, DealCreateRequest, DealDetailOut,
    DealNotesUpdateRequest, DealOut, DealOwnerUpdateRequest, DealStageEventOut, DealStageHistoryOut, DealStageUpdateRequest, DealStatusUpdateRequest,
    DealUpdateRequest, DuplicateGroupOut, EmployeeSalesRow, FollowUpPerformanceOut, ImportResultOut, LeadBulkDeleteRequest, LeadBulkOwnerRequest,
    LeadConvertRequest, LeadCreateFromConversationRequest,
    LeadCreateRequest, LeadDetailOut, LeadFunnelMonth, LeadFunnelOut, LeadOut, LeadUpdateRequest, ManagerUpdateRequest,
    MapToCustomerRequest, MergeContactsRequest, NotificationOut, PipelineCreateRequest, PipelineOut, PipelineStagesUpdateRequest, ProductSalesRow,
    ReportDrillDownRequest, ReportDrillDownResult, ReportDrillDownRow, ReportRow, ReportRunRequest, ReportRunResult, SalesTargetCreateRequest,
    SalesTargetOut, SalesTargetUpdateRequest, SavedReportCreateRequest,
    SavedReportOut, SavedReportUpdateRequest, SavedViewCreateRequest, SavedViewOut, ScoringRuleCreateRequest,
    ScoringRuleOut, ScoringRuleUpdateRequest, SearchResultRow, SearchResultsOut, TaskCreateRequest, TaskOut, TaskUpdateRequest, TerritoryCreateRequest,
    TerritoryOut, TerritoryUpdateRequest, WebFormOut, WebFormUpdateRequest,
)
from .permissions import require_channel_scope
from .services import DomainError, channel_active, log_activity, notify_user, resolve_user_entity, save_upload

logger = logging.getLogger("textzi.crm")

router = APIRouter(prefix="/v1/crm", tags=["crm"], dependencies=[Depends(require_channel_scope("crm"))])


def _require_crm(db: Session, entity_id: str) -> None:
    if not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to use leads, tickets, and customers")


def _contact_out(contact: Contact) -> ContactOut:
    return ContactOut(
        id=contact.id, wa_id=contact.wa_id, email=contact.email, name=contact.name,
        custom_attributes=contact.custom_attributes or {}, opted_out=contact.opted_out,
        company_id=contact.company_id,
        consent_given_at=contact.consent_given_at.isoformat() if contact.consent_given_at else None,
        consent_source=contact.consent_source, crm_contact_id=contact.crm_contact_id, created_at=contact.created_at.isoformat(),
    )


def _crm_contact_out(contact: CrmContact) -> CrmContactOut:
    return CrmContactOut(
        id=contact.id, name=contact.name, phone=contact.phone, email=contact.email, title=contact.title,
        company_id=contact.company_id, owner_user_id=contact.owner_user_id, address=contact.address,
        reports_to_id=contact.reports_to_id, source=contact.source, custom_fields=contact.custom_fields or {},
        consent_given_at=contact.consent_given_at.isoformat() if contact.consent_given_at else None,
        consent_source=contact.consent_source, created_at=contact.created_at.isoformat(),
    )


def _lead_out(lead: Lead, contact: CrmContact) -> LeadOut:
    return LeadOut(
        id=lead.id, contact=_crm_contact_out(contact), company_name=lead.company_name, source=lead.source, status=lead.status,
        owner_user_id=lead.owner_user_id, notes=lead.notes, custom_fields=lead.custom_fields or {}, score=lead.score,
        converted_at=lead.converted_at.isoformat() if lead.converted_at else None, converted_deal_id=lead.converted_deal_id,
        created_at=lead.created_at.isoformat(),
    )


def _deal_out(deal: Deal, contact: CrmContact) -> DealOut:
    return DealOut(
        id=deal.id, name=deal.name, contact=_crm_contact_out(contact), pipeline_id=deal.pipeline_id, stage=deal.stage, source=deal.source,
        converted_from_conversation_id=deal.converted_from_conversation_id, converted_from_lead_id=deal.converted_from_lead_id,
        owner_user_id=deal.owner_user_id, notes=deal.notes, value=float(deal.value) if deal.value is not None else None,
        probability=deal.probability, expected_close_date=deal.expected_close_date.isoformat() if deal.expected_close_date else None,
        status=deal.status, lost_reason=deal.lost_reason, next_step=deal.next_step,
        next_step_due_at=deal.next_step_due_at.isoformat() if deal.next_step_due_at else None,
        custom_fields=deal.custom_fields or {}, stage_approvals=deal.stage_approvals or {}, created_at=deal.created_at.isoformat(),
    )


def _open_deal_stage_event(db: Session, deal: Deal, changed_by_user_id: str | None = None) -> None:
    db.add(DealStageEvent(entity_id=deal.entity_id, deal_id=deal.id, stage=deal.stage, changed_by_user_id=changed_by_user_id))


def _close_open_deal_stage_event(db: Session, deal_id: str) -> None:
    open_event = db.scalar(
        select(DealStageEvent).where(DealStageEvent.deal_id == deal_id, DealStageEvent.exited_at.is_(None))
        .order_by(DealStageEvent.entered_at.desc()),
    )
    if open_event:
        open_event.exited_at = datetime.now(timezone.utc)


def _customer_out(customer: Customer, contact: CrmContact) -> CustomerOut:
    return CustomerOut(
        id=customer.id, contact=_crm_contact_out(contact), deal_id=customer.deal_id,
        converted_from_conversation_id=customer.converted_from_conversation_id, owner_user_id=customer.owner_user_id,
        notes=customer.notes, custom_fields=customer.custom_fields or {}, created_at=customer.created_at.isoformat(),
    )


def _check_duplicate_contact(db: Session, entity_id: str, contact_id: str) -> None:
    """Blocks creating a second open Lead/Deal for a contact that already has one -- reuses the
    same "block duplicate conversion" precedent as the conversation/contact convert-to-lead
    endpoints below, just applied at creation time too."""
    existing_lead = db.scalar(select(Lead).where(Lead.contact_id == contact_id, Lead.entity_id == entity_id, Lead.status.notin_(["converted", "unqualified"])))
    if existing_lead:
        raise HTTPException(status_code=409, detail={"message": "This contact already has an open lead", "existing_lead_id": existing_lead.id})
    existing_deal = db.scalar(select(Deal).where(Deal.contact_id == contact_id, Deal.entity_id == entity_id, Deal.status == "open"))
    if existing_deal:
        raise HTTPException(status_code=409, detail={"message": "This contact already has an open deal", "existing_deal_id": existing_deal.id})


def _get_or_create_default_pipeline(db: Session, entity_id: str) -> Pipeline:
    """Creates a "Default" Pipeline row the first time one is needed, seeded from the standard
    stage/probability/forecast-category set (CrmSettings.pipeline_stages predates per-stage
    probability and is no longer a valid seed shape, so it's not consulted here)."""
    pipeline = db.scalar(select(Pipeline).where(Pipeline.entity_id == entity_id).order_by(Pipeline.created_at.asc()))
    if pipeline:
        return pipeline
    pipeline = Pipeline(entity_id=entity_id, name="Default", stages=list(DEFAULT_CRM_PIPELINE_STAGES))
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    return pipeline


def _pipeline_stages(pipeline: Pipeline) -> list[dict]:
    # Pipelines created before per-stage probability/forecast_category existed stored `stages` as
    # a flat list[str] -- normalize those on read instead of a one-off migration script, since a
    # pipeline this old may still be edited/reordered by stage name alone.
    stages = pipeline.stages
    if stages and isinstance(stages[0], str):
        stages = [{"name": s, "probability": 50, "forecast_category": "pipeline"} for s in stages]
    return stages


def _pipeline_out(pipeline: Pipeline) -> PipelineOut:
    return PipelineOut(id=pipeline.id, name=pipeline.name, stages=_pipeline_stages(pipeline))


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _get_owned_conversation(db: Session, entity_id: str, conversation_id: str) -> tuple[Conversation, Contact]:
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.entity_id == entity_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    contact = db.get(Contact, conversation.contact_id)
    return conversation, contact


def _get_or_create_settings(db: Session, entity_id: str) -> CrmSettings:
    settings_row = db.get(CrmSettings, entity_id)
    if not settings_row:
        settings_row = CrmSettings(entity_id=entity_id)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def _settings_out(settings_row: CrmSettings) -> CrmSettingsOut:
    return CrmSettingsOut(
        pipeline_stages=settings_row.pipeline_stages, notify_email=settings_row.notify_email,
        notify_sms=settings_row.notify_sms, notify_whatsapp=settings_row.notify_whatsapp,
        logo_url="/v1/crm/settings/logo" if settings_row.logo_path else None, brand_color=settings_row.brand_color,
        quote_approval_threshold=float(settings_row.quote_approval_threshold) if settings_row.quote_approval_threshold is not None else None,
        quote_approver_user_ids=settings_row.quote_approver_user_ids or [],
    )


def _get_owned_contact(db: Session, entity_id: str, contact_id: str) -> Contact:
    """WABA's own Contact -- used only where this module reads/writes the WhatsApp-side record
    directly (consent, DPDP, company grouping, map-to-customer). CRM entities (Lead/Deal/
    Customer/Task/Attachment) never point at this table -- see _get_owned_crm_contact below."""
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


def _get_owned_crm_contact(db: Session, entity_id: str, contact_id: str) -> CrmContact:
    contact = db.get(CrmContact, contact_id)
    if not contact or contact.entity_id != entity_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


def _resolve_or_create_contact(db: Session, entity_id: str, contact_id: str | None, name: str | None, phone: str | None, email: str | None, title: str | None = None) -> CrmContact:
    """Backs every "New Lead/Deal/Customer" quick-create dialog -- an agent can either pick an
    existing CrmContact (contact_id) or just type a name/phone/email and get one found-or-created
    on the spot, same as Zoho/Salesforce's own "Quick Create" forms. phone is a plain field here,
    not a WhatsApp id -- sending a message to this contact later resolves/creates the WABA Contact
    just-in-time from this number (waba_dispatch._resolve_send_target already does this for any
    wa_id it hasn't seen), so nothing about "reachable over WhatsApp" is lost by keeping this
    contact CRM-native until someone actually messages them."""
    if contact_id:
        return _get_owned_crm_contact(db, entity_id, contact_id)
    if not name or not name.strip():
        raise HTTPException(status_code=422, detail="Provide either contact_id or a name")
    existing = None
    if phone:
        existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.phone == phone))
    if not existing and email:
        existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.email == email))
    if existing:
        return existing
    contact = CrmContact(entity_id=entity_id, name=name.strip(), phone=phone, email=email, title=title, source="manual")
    db.add(contact)
    db.flush()
    return contact


def _get_or_create_crm_contact_from_waba(db: Session, entity_id: str, waba_contact: Contact, title: str | None = None) -> CrmContact:
    """The one place a WhatsApp contact becomes a CRM contact -- called by every conversion
    endpoint (convert-to-lead/deal/customer). Reuses the link if this WABA contact was already
    converted before (Contact.crm_contact_id); otherwise finds-or-creates a CrmContact by phone/
    email (same dedup as _resolve_or_create_contact, so a manually-added CRM contact and a later
    WhatsApp conversion from the same number/email land on the same CrmContact) and sets the
    link."""
    if waba_contact.crm_contact_id:
        return db.get(CrmContact, waba_contact.crm_contact_id)
    existing = None
    if waba_contact.wa_id:
        existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.phone == waba_contact.wa_id))
    if not existing and waba_contact.email:
        existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.email == waba_contact.email))
    if existing:
        crm_contact = existing
    else:
        crm_contact = CrmContact(
            entity_id=entity_id, name=waba_contact.name, phone=waba_contact.wa_id, email=waba_contact.email,
            title=title, company_id=waba_contact.company_id, source="whatsapp_conversation",
            consent_given_at=waba_contact.consent_given_at, consent_source=waba_contact.consent_source,
        )
        db.add(crm_contact)
        db.flush()
    waba_contact.crm_contact_id = crm_contact.id
    return crm_contact


def _linked_waba_contact(db: Session, entity_id: str, crm_contact_id: str) -> Contact | None:
    """Reverse of the link above -- used when a CRM action (e.g. converting a Deal to a Customer)
    should also update the originating WhatsApp contact, if one exists. A CRM-native contact with
    no WhatsApp origin simply has none, and that's fine."""
    return db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.crm_contact_id == crm_contact_id))


def _recent_activity(db: Session, entity_id: str, crm_contact_id: str, limit: int = 15) -> tuple[str | None, list[ActivityMessageOut]]:
    """Backs the Lead/Deal detail pages' activity timeline -- Zoho/SF both lead a record's page
    with a chronological feed of every call/email/message, which this codebase had nowhere to
    show before (only Contact.detail had funnel history, and even that never included the actual
    WhatsApp/email messages). Only WABA-linked contacts have anything to show; a CRM-native
    lead/deal with no WhatsApp/email history simply gets an empty list."""
    waba_contact = _linked_waba_contact(db, entity_id, crm_contact_id)
    if not waba_contact:
        return None, []
    conversation_ids = db.scalars(select(Conversation.id).where(Conversation.contact_id == waba_contact.id)).all()
    if not conversation_ids:
        return waba_contact.id, []
    messages = db.scalars(
        select(ConversationMessage).where(ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.is_private.is_(False))
        .order_by(ConversationMessage.created_at.desc()).limit(limit),
    ).all()
    conv_channel = {c.id: c.channel for c in db.scalars(select(Conversation).where(Conversation.id.in_(conversation_ids))).all()}
    return waba_contact.id, [
        ActivityMessageOut(
            id=m.id, channel=conv_channel.get(m.conversation_id, 'whatsapp'), direction=m.direction, message_type=m.message_type,
            body=m.body, created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]


@router.get("/status")
def get_crm_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Lightweight, no-422 status check -- lets the frontend nav decide whether to show the CRM
    menu group without having to interpret a failed /leads call as "not subscribed"."""
    entity = _resolve_entity(db, user)
    return {"active": channel_active(db, entity.id, "crm")}


@router.get("/search", response_model=SearchResultsOut)
def search_crm(q: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Backs the navbar global-search box -- a small, grouped ilike search across CRM's own
    entities (Leads/Deals/Contacts/Companies). WABA contacts have their own directory search
    already; not folded in here."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    q = q.strip()
    if len(q) < 2:
        return SearchResultsOut(leads=[], deals=[], contacts=[], companies=[])
    like = f"%{q}%"

    contacts = db.scalars(
        select(CrmContact).where(
            CrmContact.entity_id == entity.id,
            (CrmContact.name.ilike(like)) | (CrmContact.email.ilike(like)) | (CrmContact.phone.ilike(like)),
        ).limit(5),
    ).all()

    leads = db.scalars(
        select(Lead).join(CrmContact, CrmContact.id == Lead.contact_id).where(
            Lead.entity_id == entity.id,
            (CrmContact.name.ilike(like)) | (CrmContact.phone.ilike(like)) | (Lead.company_name.ilike(like)),
        ).limit(5),
    ).all()
    lead_contacts = {c.id: c for c in db.scalars(select(CrmContact).where(CrmContact.id.in_([l.contact_id for l in leads]))).all()} if leads else {}

    deals = db.scalars(
        select(Deal).join(CrmContact, CrmContact.id == Deal.contact_id).where(
            Deal.entity_id == entity.id, (CrmContact.name.ilike(like)) | (CrmContact.phone.ilike(like)),
        ).limit(5),
    ).all()
    deal_contacts = {c.id: c for c in db.scalars(select(CrmContact).where(CrmContact.id.in_([d.contact_id for d in deals]))).all()} if deals else {}

    companies = db.scalars(select(Company).where(Company.entity_id == entity.id, Company.name.ilike(like)).limit(5)).all()

    return SearchResultsOut(
        leads=[SearchResultRow(id=l.id, label=lead_contacts[l.contact_id].name or lead_contacts[l.contact_id].phone or "Lead", sublabel=l.company_name) for l in leads],
        deals=[SearchResultRow(id=d.id, label=deal_contacts[d.contact_id].name or deal_contacts[d.contact_id].phone or "Deal", sublabel=f"₹{d.value:,.0f}" if d.value else d.stage) for d in deals],
        contacts=[SearchResultRow(id=c.id, label=c.name or c.phone or "Contact", sublabel=c.email or c.phone) for c in contacts],
        companies=[SearchResultRow(id=c.id, label=c.name, sublabel=c.industry) for c in companies],
    )


# --- CRM contacts -- CRM's own person record, first-class alongside Leads/Deals (matches Zoho's
# own Contacts nav item) --------------------------------------------------------------------

@router.get("/contacts", response_model=list[CrmContactOut])
def list_crm_contacts(search: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(CrmContact).where(CrmContact.entity_id == entity.id)
    if search:
        like = f"%{search}%"
        query = query.where((CrmContact.name.ilike(like)) | (CrmContact.email.ilike(like)) | (CrmContact.phone.ilike(like)))
    contacts = db.scalars(query.order_by(CrmContact.created_at.desc())).all()
    return [_crm_contact_out(c) for c in contacts]


@router.get("/contacts/duplicates", response_model=list[DuplicateGroupOut])
def find_duplicate_contacts(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Groups contacts sharing the same phone or email -- e.g. one entered manually and a second
    created later from a WhatsApp conversion off the same number. Not a fuzzy-name matcher (that's
    a much bigger, error-prone feature); phone/email equality is the same conservative dedup rule
    already used everywhere else in this module (_resolve_or_create_contact, import above).
    Declared ahead of GET /contacts/{contact_id} below -- "duplicates" would otherwise match that
    route's {contact_id} path param first and 404 as if it were a literal contact id."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contacts = db.scalars(select(CrmContact).where(CrmContact.entity_id == entity.id)).all()
    by_phone: dict[str, list[CrmContact]] = {}
    by_email: dict[str, list[CrmContact]] = {}
    for c in contacts:
        if c.phone:
            by_phone.setdefault(c.phone, []).append(c)
        if c.email:
            by_email.setdefault(c.email.lower(), []).append(c)
    groups: list[DuplicateGroupOut] = []
    already_grouped: set[str] = set()
    for phone_group in by_phone.values():
        if len(phone_group) > 1:
            groups.append(DuplicateGroupOut(match_on="phone", contacts=[_crm_contact_out(c) for c in phone_group]))
            already_grouped.update(c.id for c in phone_group)
    for email_group in by_email.values():
        ids = {c.id for c in email_group}
        if len(email_group) > 1 and not ids.issubset(already_grouped):
            groups.append(DuplicateGroupOut(match_on="email", contacts=[_crm_contact_out(c) for c in email_group]))
    return groups


@router.get("/contacts/{contact_id}", response_model=CrmContactOut)
def get_crm_contact(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    return _crm_contact_out(_get_owned_crm_contact(db, entity.id, contact_id))


@router.post("/contacts", response_model=CrmContactOut)
def create_crm_contact(payload: CrmContactCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = CrmContact(
        entity_id=entity.id, name=payload.name.strip(), phone=payload.phone, email=payload.email, title=payload.title,
        company_id=payload.company_id, owner_user_id=payload.owner_user_id, address=payload.address,
        reports_to_id=payload.reports_to_id, source=payload.source, custom_fields=payload.custom_fields or {},
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return _crm_contact_out(contact)


@router.patch("/contacts/{contact_id}", response_model=CrmContactOut)
def update_crm_contact(contact_id: str, payload: CrmContactUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _get_owned_crm_contact(db, entity.id, contact_id)
    if "reports_to_id" in payload.model_fields_set and payload.reports_to_id == contact_id:
        raise HTTPException(status_code=422, detail="A contact cannot report to themselves")
    if "name" in payload.model_fields_set and payload.name:
        contact.name = payload.name
    if "phone" in payload.model_fields_set:
        contact.phone = payload.phone
    if "email" in payload.model_fields_set:
        contact.email = payload.email
    if "title" in payload.model_fields_set:
        contact.title = payload.title
    if "company_id" in payload.model_fields_set:
        contact.company_id = payload.company_id
    if "owner_user_id" in payload.model_fields_set:
        contact.owner_user_id = payload.owner_user_id
    if "address" in payload.model_fields_set:
        contact.address = payload.address
    if "reports_to_id" in payload.model_fields_set:
        contact.reports_to_id = payload.reports_to_id
    if "custom_fields" in payload.model_fields_set and payload.custom_fields is not None:
        contact.custom_fields = payload.custom_fields
    db.commit()
    db.refresh(contact)
    return _crm_contact_out(contact)


@router.post("/contacts/import", response_model=ImportResultOut)
def import_contacts(file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Bulk CSV import -- expects a header row with name,phone,email,title,company columns (only
    name is required). A row whose phone or email already matches an existing contact is skipped,
    not overwritten -- re-uploading the same file twice is always safe. Deliberately a plain
    fixed-header CSV, not Zoho's full column-mapping wizard -- the same SME-scope simplification
    made throughout this codebase (see Quote's own "not IRN e-invoicing" note) applied to import."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    raw = file.file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    created = 0
    skipped = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        phone = (row.get("phone") or "").strip() or None
        email = (row.get("email") or "").strip() or None
        title = (row.get("title") or "").strip() or None
        company_name = (row.get("company") or "").strip() or None
        if not name:
            errors.append(f"Row {i}: missing name")
            skipped += 1
            continue
        existing = None
        if phone:
            existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity.id, CrmContact.phone == phone))
        if not existing and email:
            existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity.id, CrmContact.email == email))
        if existing:
            skipped += 1
            continue
        company_id = None
        if company_name:
            company = db.scalar(select(Company).where(Company.entity_id == entity.id, Company.name == company_name))
            if not company:
                company = Company(entity_id=entity.id, name=company_name)
                db.add(company)
                db.flush()
            company_id = company.id
        db.add(CrmContact(entity_id=entity.id, name=name, phone=phone, email=email, title=title, company_id=company_id, source="csv_import"))
        created += 1
    db.commit()
    return ImportResultOut(created=created, skipped=skipped, errors=errors[:20])


@router.post("/leads/import", response_model=ImportResultOut)
def import_leads(file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Same fixed-header CSV contract as /contacts/import, but creates thin Leads (company goes
    into Lead.company_name free text, same as the New Lead dialog, not a linked Company record --
    a raw imported lead's business often isn't a real account yet)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    raw = file.file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    created = 0
    skipped = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        phone = (row.get("phone") or "").strip() or None
        email = (row.get("email") or "").strip() or None
        title = (row.get("title") or "").strip() or None
        company_name = (row.get("company") or "").strip() or None
        if not name:
            errors.append(f"Row {i}: missing name")
            skipped += 1
            continue
        contact = _resolve_or_create_contact(db, entity.id, None, name, phone, email, title)
        existing_lead = db.scalar(select(Lead).where(Lead.contact_id == contact.id, Lead.entity_id == entity.id, Lead.status.notin_(["converted", "unqualified"])))
        existing_deal = db.scalar(select(Deal).where(Deal.contact_id == contact.id, Deal.entity_id == entity.id, Deal.status == "open"))
        if existing_lead or existing_deal:
            skipped += 1
            continue
        lead = Lead(entity_id=entity.id, contact_id=contact.id, company_name=company_name, source="csv_import")
        db.add(lead)
        db.flush()
        apply_lead_routing(db, lead, contact)
        rescore_lead(db, lead)
        created += 1
    db.commit()
    return ImportResultOut(created=created, skipped=skipped, errors=errors[:20])


@router.post("/contacts/merge", response_model=CrmContactOut)
def merge_contacts(payload: MergeContactsRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Reassigns every Lead/Deal/Customer/Task/Attachment (and the reverse WhatsApp-contact link)
    from each duplicate onto the primary contact, filling any blank primary field from the
    duplicate along the way, then deletes the duplicate rows. One real merged contact with
    combined history, not two contacts pretending to be different people."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    if payload.primary_id in payload.duplicate_ids:
        raise HTTPException(status_code=422, detail="Primary contact can't also be listed as a duplicate")
    primary = _get_owned_crm_contact(db, entity.id, payload.primary_id)
    for dup_id in payload.duplicate_ids:
        dup = _get_owned_crm_contact(db, entity.id, dup_id)
        db.query(Lead).filter(Lead.contact_id == dup.id).update({"contact_id": primary.id})
        db.query(Deal).filter(Deal.contact_id == dup.id).update({"contact_id": primary.id})
        db.query(Customer).filter(Customer.contact_id == dup.id).update({"contact_id": primary.id})
        db.query(Task).filter(Task.contact_id == dup.id).update({"contact_id": primary.id})
        db.query(Attachment).filter(Attachment.contact_id == dup.id).update({"contact_id": primary.id})
        db.query(Contact).filter(Contact.crm_contact_id == dup.id).update({"crm_contact_id": primary.id})
        # Anyone who reports to the duplicate now reports to the primary instead -- otherwise
        # merging away a "manager" contact would silently orphan their direct reports.
        db.query(CrmContact).filter(CrmContact.reports_to_id == dup.id).update({"reports_to_id": primary.id})
        primary.email = primary.email or dup.email
        primary.phone = primary.phone or dup.phone
        primary.company_id = primary.company_id or dup.company_id
        primary.title = primary.title or dup.title
        primary.address = primary.address or dup.address
        primary.owner_user_id = primary.owner_user_id or dup.owner_user_id
        if not primary.reports_to_id and dup.reports_to_id and dup.reports_to_id != primary.id:
            primary.reports_to_id = dup.reports_to_id
        db.delete(dup)
    db.commit()
    db.refresh(primary)
    return _crm_contact_out(primary)


@router.get("/contacts/{contact_id}/detail", response_model=CrmContactDetailOut)
def get_crm_contact_detail(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Richer sibling of GET /contacts/{id} above -- that one stays thin (crm-tasks.vue depends on
    its current shape for label lookups), this one backs the record detail page with every
    Lead/Deal/Customer/Task/Attachment this contact has, plus a deep-link to its WhatsApp thread
    if it was ever converted from one (Contact.crm_contact_id, reverse-looked-up)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _get_owned_crm_contact(db, entity.id, contact_id)
    company = db.get(Company, contact.company_id) if contact.company_id else None
    leads = db.scalars(select(Lead).where(Lead.contact_id == contact_id).order_by(Lead.created_at.desc())).all()
    deals = db.scalars(select(Deal).where(Deal.contact_id == contact_id).order_by(Deal.created_at.desc())).all()
    customers = db.scalars(select(Customer).where(Customer.contact_id == contact_id)).all()
    tasks = db.scalars(select(Task).where(Task.contact_id == contact_id).order_by(Task.due_at.asc().nulls_last())).all()
    attachments = db.scalars(select(Attachment).where(Attachment.contact_id == contact_id)).all()
    waba_contact = _linked_waba_contact(db, entity.id, contact_id)
    reports_to = db.get(CrmContact, contact.reports_to_id) if contact.reports_to_id else None
    direct_reports = db.scalars(select(CrmContact).where(CrmContact.reports_to_id == contact_id)).all()
    return CrmContactDetailOut(
        contact=_crm_contact_out(contact), company=_company_out(db, company) if company else None,
        leads=[_lead_out(l, contact) for l in leads], deals=[_deal_out(d, contact) for d in deals],
        customers=[_customer_out(c, contact) for c in customers], tasks=[_task_out(t) for t in tasks],
        attachments=[_attachment_out(a) for a in attachments], waba_contact_id=waba_contact.id if waba_contact else None,
        reports_to=_crm_contact_out(reports_to) if reports_to else None,
        direct_reports=[_crm_contact_out(c) for c in direct_reports],
    )


@router.get("/leads", response_model=list[LeadOut])
def list_leads(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    leads = db.scalars(select(Lead).where(Lead.entity_id == entity.id).order_by(Lead.created_at.desc())).all()
    contacts = {c.id: c for c in db.scalars(select(CrmContact).where(CrmContact.id.in_([lead.contact_id for lead in leads]))).all()} if leads else {}
    return [_lead_out(lead, contacts[lead.contact_id]) for lead in leads]


@router.post("/leads", response_model=LeadOut)
def create_lead(payload: LeadCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _resolve_or_create_contact(db, entity.id, payload.contact_id, payload.name, payload.phone, payload.email, payload.title)
    _check_duplicate_contact(db, entity.id, contact.id)
    lead = Lead(
        entity_id=entity.id, contact_id=contact.id, company_name=payload.company_name, source=payload.source,
        owner_user_id=payload.owner_user_id, notes=payload.notes, custom_fields=payload.custom_fields or {},
    )
    db.add(lead)
    db.flush()
    apply_lead_routing(db, lead, contact)
    rescore_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, contact)


@router.get("/leads/{lead_id}", response_model=LeadDetailOut)
def get_lead(lead_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    contact = db.get(CrmContact, lead.contact_id)
    company = db.get(Company, contact.company_id) if contact.company_id else None
    tasks = db.scalars(select(Task).where(Task.contact_id == lead.contact_id).order_by(Task.due_at.asc().nulls_last())).all()
    waba_contact_id, recent_messages = _recent_activity(db, entity.id, lead.contact_id)
    return LeadDetailOut(
        lead=_lead_out(lead, contact), company=_company_out(db, company) if company else None,
        tasks=[_task_out(t) for t in tasks], waba_contact_id=waba_contact_id, recent_messages=recent_messages,
    )


@router.delete("/leads/{lead_id}")
def delete_lead(lead_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status == "converted":
        raise HTTPException(status_code=409, detail="This lead was already converted to a deal -- delete the deal instead")
    db.delete(lead)
    db.commit()
    return {"deleted": True}


@router.post("/leads/bulk-owner", response_model=list[LeadOut])
def bulk_update_lead_owner(payload: LeadBulkOwnerRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    leads = db.scalars(select(Lead).where(Lead.id.in_(payload.lead_ids), Lead.entity_id == entity.id)).all()
    contacts = {c.id: c for c in db.scalars(select(CrmContact).where(CrmContact.id.in_([l.contact_id for l in leads]))).all()} if leads else {}
    for lead in leads:
        if payload.owner_user_id and payload.owner_user_id != lead.owner_user_id:
            contact = contacts.get(lead.contact_id)
            notify_user(db, entity.id, payload.owner_user_id, "lead_assigned", "Lead assigned to you", f"{contact.name if contact else 'A lead'} was assigned to you", f"/crm-leads/{lead.id}")
        lead.owner_user_id = payload.owner_user_id
    db.commit()
    return [_lead_out(l, contacts[l.contact_id]) for l in leads]


@router.post("/leads/bulk-delete")
def bulk_delete_leads(payload: LeadBulkDeleteRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    leads = db.scalars(select(Lead).where(Lead.id.in_(payload.lead_ids), Lead.entity_id == entity.id)).all()
    deletable = [l for l in leads if l.status != "converted"]
    for lead in deletable:
        db.delete(lead)
    db.commit()
    return {"deleted": len(deletable), "skipped": len(leads) - len(deletable)}


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: str, payload: LeadUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if "company_name" in payload.model_fields_set:
        lead.company_name = payload.company_name
    if "status" in payload.model_fields_set and payload.status:
        lead.status = payload.status
    if "owner_user_id" in payload.model_fields_set:
        if payload.owner_user_id and payload.owner_user_id != lead.owner_user_id:
            contact = db.get(CrmContact, lead.contact_id)
            notify_user(db, entity.id, payload.owner_user_id, "lead_assigned", "Lead assigned to you", f"{contact.name if contact else 'A lead'} was assigned to you", f"/crm-leads/{lead.id}")
        lead.owner_user_id = payload.owner_user_id
    if "notes" in payload.model_fields_set:
        lead.notes = payload.notes
    if "custom_fields" in payload.model_fields_set and payload.custom_fields is not None:
        lead.custom_fields = payload.custom_fields
        rescore_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(CrmContact, lead.contact_id))


@router.post("/leads/{lead_id}/convert", response_model=DealOut)
def convert_lead_to_deal(lead_id: str, payload: LeadConvertRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The one explicit "Convert" action a full Lead/Deal split requires (Zoho/Salesforce
    convention) -- creates a real Deal from this Lead's contact and marks the Lead converted,
    rather than mutating the Lead in place into something deal-shaped."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status == "converted":
        raise HTTPException(status_code=409, detail="This lead was already converted to a deal")
    contact = db.get(CrmContact, lead.contact_id)
    deal = Deal(
        entity_id=entity.id, contact_id=lead.contact_id, name=payload.deal_name,
        pipeline_id=payload.pipeline_id or _get_or_create_default_pipeline(db, entity.id).id, stage=payload.stage,
        source=lead.source, converted_from_lead_id=lead.id, owner_user_id=lead.owner_user_id, notes=lead.notes,
        value=payload.value, probability=payload.probability,
        expected_close_date=datetime.fromisoformat(payload.expected_close_date) if payload.expected_close_date else None,
    )
    db.add(deal)
    db.flush()
    _open_deal_stage_event(db, deal)
    lead.status = "converted"
    lead.converted_at = datetime.now(timezone.utc)
    lead.converted_deal_id = deal.id
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, contact)


@router.get("/deals", response_model=list[DealOut])
def list_deals(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deals = db.scalars(select(Deal).where(Deal.entity_id == entity.id).order_by(Deal.created_at.desc())).all()
    contacts = {c.id: c for c in db.scalars(select(CrmContact).where(CrmContact.id.in_([deal.contact_id for deal in deals]))).all()} if deals else {}
    return [_deal_out(deal, contacts[deal.contact_id]) for deal in deals]


@router.post("/deals", response_model=DealOut)
def create_deal(payload: DealCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Standalone deal creation for the "New Deal" button on the Deals page -- every other deal
    entry point (lead convert, conversation/contact convert) already has its own owning contact
    to work from; this is the one path that may need to find-or-create a contact on the spot."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _resolve_or_create_contact(db, entity.id, payload.contact_id, payload.name, payload.phone, payload.email, payload.title)
    deal = Deal(
        entity_id=entity.id, contact_id=contact.id, name=payload.deal_name, source="manual",
        pipeline_id=payload.pipeline_id or _get_or_create_default_pipeline(db, entity.id).id, stage=payload.stage,
        value=payload.value, probability=payload.probability, owner_user_id=payload.owner_user_id, notes=payload.notes,
        custom_fields=payload.custom_fields or {},
    )
    db.add(deal)
    db.flush()
    _open_deal_stage_event(db, deal)
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, contact)


@router.get("/deals/{deal_id}", response_model=DealDetailOut)
def get_deal(deal_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    contact = db.get(CrmContact, deal.contact_id)
    company = db.get(Company, contact.company_id) if contact.company_id else None
    tasks = db.scalars(select(Task).where(Task.deal_id == deal_id).order_by(Task.due_at.asc().nulls_last())).all()
    quotes = db.scalars(select(Quote).where(Quote.deal_id == deal_id).order_by(Quote.created_at.desc())).all()
    waba_contact_id, recent_messages = _recent_activity(db, entity.id, deal.contact_id)
    return DealDetailOut(
        deal=_deal_out(deal, contact), company=_company_out(db, company) if company else None,
        tasks=[_task_out(t) for t in tasks], quotes=[_quote_out(db, q) for q in quotes],
        waba_contact_id=waba_contact_id, recent_messages=recent_messages,
    )


@router.delete("/deals/{deal_id}")
def delete_deal(deal_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if db.scalar(select(Quote).where(Quote.deal_id == deal_id)):
        raise HTTPException(status_code=409, detail="Delete this deal's quotes first")
    db.query(Customer).filter(Customer.deal_id == deal_id).update({"deal_id": None})
    db.query(Task).filter(Task.deal_id == deal_id).update({"deal_id": None})
    db.query(Lead).filter(Lead.converted_deal_id == deal_id).update({"converted_deal_id": None})
    db.query(DealStageEvent).filter(DealStageEvent.deal_id == deal_id).delete()
    db.delete(deal)
    db.commit()
    return {"deleted": True}


@router.post("/deals/bulk-owner", response_model=list[DealOut])
def bulk_update_deal_owner(payload: DealBulkOwnerRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deals = db.scalars(select(Deal).where(Deal.id.in_(payload.deal_ids), Deal.entity_id == entity.id)).all()
    for deal in deals:
        deal.owner_user_id = payload.owner_user_id
    db.commit()
    contacts = {c.id: c for c in db.scalars(select(CrmContact).where(CrmContact.id.in_([d.contact_id for d in deals]))).all()} if deals else {}
    return [_deal_out(d, contacts[d.contact_id]) for d in deals]


@router.post("/deals/bulk-delete")
def bulk_delete_deals(payload: DealBulkDeleteRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deals = db.scalars(select(Deal).where(Deal.id.in_(payload.deal_ids), Deal.entity_id == entity.id)).all()
    quoted_deal_ids = {q.deal_id for q in db.scalars(select(Quote).where(Quote.deal_id.in_(payload.deal_ids))).all()}
    deletable = [d for d in deals if d.id not in quoted_deal_ids]
    ids = [d.id for d in deletable]
    if ids:
        db.query(Customer).filter(Customer.deal_id.in_(ids)).update({"deal_id": None}, synchronize_session=False)
        db.query(Task).filter(Task.deal_id.in_(ids)).update({"deal_id": None}, synchronize_session=False)
        db.query(Lead).filter(Lead.converted_deal_id.in_(ids)).update({"converted_deal_id": None}, synchronize_session=False)
        db.query(DealStageEvent).filter(DealStageEvent.deal_id.in_(ids)).delete(synchronize_session=False)
    for deal in deletable:
        db.delete(deal)
    db.commit()
    return {"deleted": len(deletable), "skipped": len(deals) - len(deletable)}


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    customers = db.scalars(select(Customer).where(Customer.entity_id == entity.id).order_by(Customer.created_at.desc())).all()
    contacts = {c.id: c for c in db.scalars(select(CrmContact).where(CrmContact.id.in_([customer.contact_id for customer in customers]))).all()} if customers else {}
    return [_customer_out(customer, contacts[customer.contact_id]) for customer in customers]


@router.post("/customers", response_model=CustomerOut)
def create_customer(payload: CustomerCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Standalone customer creation for the "New Customer" button -- e.g. a customer onboarded
    outside WhatsApp entirely (phone call, walk-in) who should still show up in the CRM."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _resolve_or_create_contact(db, entity.id, payload.contact_id, payload.name, payload.phone, payload.email, payload.title)
    if db.scalar(select(Customer).where(Customer.contact_id == contact.id)):
        raise HTTPException(status_code=409, detail="This contact is already linked to a customer")
    customer = Customer(
        entity_id=entity.id, contact_id=contact.id, owner_user_id=payload.owner_user_id, notes=payload.notes,
        custom_fields=payload.custom_fields or {},
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    # If this CrmContact originated from (or was later linked to) a WhatsApp contact, mark that
    # WhatsApp contact as belonging to this new Customer too -- future messages from that number
    # get recognized as this same customer (WABA's own Contact.customer_id bridge, unchanged).
    waba_contact = _linked_waba_contact(db, entity.id, contact.id)
    if waba_contact:
        waba_contact.customer_id = customer.id
        db.commit()
    return _customer_out(customer, contact)


@router.get("/customers/{customer_id}", response_model=CustomerDetailOut)
def get_customer(customer_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    customer = db.get(Customer, customer_id)
    if not customer or customer.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    contact = db.get(CrmContact, customer.contact_id)
    tasks = db.scalars(select(Task).where(Task.contact_id == customer.contact_id).order_by(Task.due_at.asc().nulls_last())).all()
    base = _customer_out(customer, contact)
    return CustomerDetailOut(**base.model_dump(), tasks=[_task_out(t) for t in tasks])


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: str, payload: CustomerUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    customer = db.get(Customer, customer_id)
    if not customer or customer.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    if "owner_user_id" in payload.model_fields_set:
        customer.owner_user_id = payload.owner_user_id
    if "notes" in payload.model_fields_set:
        customer.notes = payload.notes
    if "custom_fields" in payload.model_fields_set and payload.custom_fields is not None:
        customer.custom_fields = payload.custom_fields
    db.commit()
    db.refresh(customer)
    return _customer_out(customer, db.get(CrmContact, customer.contact_id))


@router.delete("/customers/{customer_id}")
def delete_customer(customer_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    customer = db.get(Customer, customer_id)
    if not customer or customer.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.delete(customer)
    db.commit()
    return {"deleted": True}


@router.post("/conversations/{conversation_id}/convert-to-lead", response_model=LeadOut)
def convert_conversation_to_lead(
    conversation_id: str, payload: LeadCreateFromConversationRequest = LeadCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """company_name/owner/notes come from the agent's own right-panel form -- filled in live
    during the chat rather than defaulted blind, since a lead is worth more with real context
    captured while the customer is actually available to ask."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    conversation, waba_contact = _get_owned_conversation(db, entity.id, conversation_id)
    contact = _get_or_create_crm_contact_from_waba(db, entity.id, waba_contact, payload.title)
    lead = Lead(
        entity_id=entity.id, contact_id=contact.id, source="whatsapp_conversation",
        company_name=payload.company_name, owner_user_id=payload.owner_user_id, notes=payload.notes,
    )
    db.add(lead)
    db.flush()
    apply_lead_routing(db, lead, contact)
    rescore_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, contact)


@router.post("/conversations/{conversation_id}/convert-to-deal", response_model=DealOut)
def convert_conversation_to_deal(
    conversation_id: str, payload: DealCreateFromConversationRequest = DealCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """Direct conversation -> Deal, skipping the Lead stage -- for when an agent already knows
    the contact is qualified (e.g. an inbound customer asking to buy). Same "no forced Lead-first
    requirement" principle direct-to-Customer conversion already established."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    conversation, waba_contact = _get_owned_conversation(db, entity.id, conversation_id)
    existing = db.scalar(select(Deal).where(Deal.converted_from_conversation_id == conversation_id))
    if existing:
        raise HTTPException(status_code=409, detail="This conversation was already converted to a deal")
    contact = _get_or_create_crm_contact_from_waba(db, entity.id, waba_contact)
    deal = Deal(
        entity_id=entity.id, contact_id=contact.id, name=payload.deal_name, source="whatsapp_conversation", converted_from_conversation_id=conversation_id,
        pipeline_id=payload.pipeline_id or _get_or_create_default_pipeline(db, entity.id).id, stage=payload.stage, value=payload.value, probability=payload.probability,
        owner_user_id=payload.owner_user_id, notes=payload.notes,
    )
    db.add(deal)
    db.flush()
    _open_deal_stage_event(db, deal)
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, contact)


@router.post("/conversations/{conversation_id}/convert-to-customer", response_model=CustomerOut)
def convert_conversation_to_customer(
    conversation_id: str, payload: CustomerCreateFromConversationRequest = CustomerCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """Direct conversation -> Customer, independent of the Lead/Deal pipeline -- for an existing
    customer messaging in where there's no real sales process to track."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    conversation, waba_contact = _get_owned_conversation(db, entity.id, conversation_id)
    existing = db.scalar(select(Customer).where(Customer.converted_from_conversation_id == conversation_id))
    if existing:
        raise HTTPException(status_code=409, detail="This conversation was already converted to a customer")
    contact = _get_or_create_crm_contact_from_waba(db, entity.id, waba_contact)
    customer = Customer(
        entity_id=entity.id, contact_id=contact.id, converted_from_conversation_id=conversation_id,
        owner_user_id=payload.owner_user_id, notes=payload.notes,
    )
    db.add(customer)
    db.flush()
    waba_contact.customer_id = customer.id
    db.commit()
    db.refresh(customer)
    return _customer_out(customer, contact)


@router.post("/deals/{deal_id}/convert-to-customer", response_model=CustomerOut)
def convert_deal_to_customer(deal_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    existing = db.scalar(select(Customer).where(Customer.deal_id == deal_id))
    if existing:
        raise HTTPException(status_code=409, detail="This deal was already converted to a customer")
    contact = db.get(CrmContact, deal.contact_id)
    customer = Customer(
        entity_id=entity.id, contact_id=deal.contact_id, deal_id=deal.id,
        converted_from_conversation_id=deal.converted_from_conversation_id, owner_user_id=deal.owner_user_id, notes=deal.notes,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    # See create_customer's identical comment -- keep the originating WhatsApp contact (if any)
    # in sync with the new Customer link.
    waba_contact = _linked_waba_contact(db, entity.id, contact.id)
    if waba_contact:
        waba_contact.customer_id = customer.id
        db.commit()
    return _customer_out(customer, contact)


@router.post("/contacts/{contact_id}/convert-to-lead", response_model=LeadOut)
def convert_contact_to_lead(
    contact_id: str, payload: LeadCreateFromConversationRequest = LeadCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """Same as the conversation-based conversion, but reachable from the contacts directory
    where an agent may want to create a lead without having an open conversation selected."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    waba_contact = _get_owned_contact(db, entity.id, contact_id)
    contact = _get_or_create_crm_contact_from_waba(db, entity.id, waba_contact, payload.title)
    _check_duplicate_contact(db, entity.id, contact.id)
    lead = Lead(entity_id=entity.id, contact_id=contact.id, source="manual", company_name=payload.company_name, owner_user_id=payload.owner_user_id, notes=payload.notes)
    db.add(lead)
    db.flush()
    apply_lead_routing(db, lead, contact)
    rescore_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, contact)


@router.post("/contacts/{contact_id}/convert-to-deal", response_model=DealOut)
def convert_contact_to_deal(
    contact_id: str, payload: DealCreateFromConversationRequest = DealCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """Same as the conversation-based direct-to-Deal conversion, reachable from the contacts
    directory. Duplicate-deal detection only blocks on an existing OPEN deal -- a contact whose
    earlier deal already closed (won or lost) can legitimately become a new deal (e.g. a renewal)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    waba_contact = _get_owned_contact(db, entity.id, contact_id)
    contact = _get_or_create_crm_contact_from_waba(db, entity.id, waba_contact)
    existing = db.scalar(select(Deal).where(Deal.contact_id == contact.id, Deal.entity_id == entity.id, Deal.status == "open"))
    if existing:
        raise HTTPException(status_code=409, detail=f"This contact already has an open deal (created {existing.created_at.date().isoformat()}) -- close it before creating a new one")
    deal = Deal(
        entity_id=entity.id, contact_id=contact.id, name=payload.deal_name, source="manual",
        pipeline_id=payload.pipeline_id or _get_or_create_default_pipeline(db, entity.id).id, stage=payload.stage,
        value=payload.value, probability=payload.probability, owner_user_id=payload.owner_user_id, notes=payload.notes,
    )
    db.add(deal)
    db.flush()
    _open_deal_stage_event(db, deal)
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, contact)


@router.post("/contacts/{contact_id}/convert-to-customer", response_model=CustomerOut)
def convert_contact_to_customer(
    contact_id: str, payload: CustomerCreateFromConversationRequest = CustomerCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    waba_contact = _get_owned_contact(db, entity.id, contact_id)
    contact = _get_or_create_crm_contact_from_waba(db, entity.id, waba_contact)
    if db.scalar(select(Customer).where(Customer.contact_id == contact.id)):
        raise HTTPException(status_code=409, detail="This contact is already linked to a customer")
    customer = Customer(entity_id=entity.id, contact_id=contact.id, owner_user_id=payload.owner_user_id, notes=payload.notes)
    db.add(customer)
    db.flush()
    waba_contact.customer_id = customer.id
    db.commit()
    db.refresh(customer)
    return _customer_out(customer, contact)


@router.post("/contacts/{contact_id}/map-to-customer", response_model=ContactOut)
def map_contact_to_customer(contact_id: str, payload: MapToCustomerRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Links a contact to an existing Customer instead of creating a new one -- for a customer
    who messages from a second number/contact already converted under a different one."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _get_owned_contact(db, entity.id, contact_id)
    customer = db.scalar(select(Customer).where(Customer.id == payload.customer_id, Customer.entity_id == entity.id))
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    contact.customer_id = customer.id
    db.commit()
    db.refresh(contact)
    return _contact_out(contact)


_STAGE_REQUIREMENT_LABELS = {
    "value": "Deal value", "probability": "Probability", "expected_close_date": "Expected close date", "owner_user_id": "Owner",
}


def _missing_stage_requirements(deal: Deal, pipeline: Pipeline | None) -> list[str]:
    """A lightweight "Blueprint" -- Pipeline.stages carries an optional required_fields list per
    stage; leaving that stage is blocked until they're filled. Just a field-completeness gate, not
    a process-designer graph, but it's what "can't skip stage 3 without X" needs in practice."""
    if not pipeline:
        return []
    stage_def = next((s for s in _pipeline_stages(pipeline) if s.get("name") == deal.stage), None)
    if not stage_def or not stage_def.get("required_fields"):
        return []
    missing = []
    for field in stage_def["required_fields"]:
        if field in ("value", "probability", "owner_user_id"):
            if getattr(deal, field) is None:
                missing.append(_STAGE_REQUIREMENT_LABELS[field])
        elif field == "expected_close_date":
            if deal.expected_close_date is None:
                missing.append(_STAGE_REQUIREMENT_LABELS[field])
        elif not (deal.custom_fields or {}).get(field):
            missing.append(field)
    return missing


def _missing_stage_approvals(deal: Deal, pipeline: Pipeline | None) -> list[str]:
    """User.id list still owed an approval before this deal can leave its current stage -- the
    other half of the "Blueprint" gate, alongside _missing_stage_requirements above."""
    if not pipeline:
        return []
    stage_def = next((s for s in _pipeline_stages(pipeline) if s.get("name") == deal.stage), None)
    required = (stage_def or {}).get("required_approval_user_ids") or []
    if not required:
        return []
    approved_ids = {a["user_id"] for a in (deal.stage_approvals or {}).get(deal.stage, [])}
    return [uid for uid in required if uid not in approved_ids]


@router.patch("/deals/{deal_id}/stage", response_model=DealOut)
def update_deal_stage(deal_id: str, payload: DealStageUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if deal.stage != payload.stage:
        pipeline = db.get(Pipeline, deal.pipeline_id) if deal.pipeline_id else None
        missing_fields = _missing_stage_requirements(deal, pipeline)
        if missing_fields:
            raise HTTPException(status_code=422, detail=f"Complete these fields before leaving \"{deal.stage}\": {', '.join(missing_fields)}")
        missing_approvers = _missing_stage_approvals(deal, pipeline)
        if missing_approvers:
            contact = db.get(CrmContact, deal.contact_id)
            names = []
            for uid in missing_approvers:
                approver = db.get(User, uid)
                names.append(approver.full_name if approver else uid)
                notify_user(db, entity.id, uid, "deal_stage_approval", "Deal stage needs your approval", f"{contact.name if contact else 'A deal'} needs your sign-off to leave \"{deal.stage}\"", f"/crm-deals/{deal.id}")
            db.commit()
            raise HTTPException(status_code=422, detail=f"Needs approval from: {', '.join(names)}")
        _close_open_deal_stage_event(db, deal.id)
        deal.stage = payload.stage
        _open_deal_stage_event(db, deal, changed_by_user_id=user.id)
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, db.get(CrmContact, deal.contact_id))


@router.post("/deals/{deal_id}/stage-approvals/approve", response_model=DealOut)
def approve_deal_stage(deal_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    pipeline = db.get(Pipeline, deal.pipeline_id) if deal.pipeline_id else None
    stage_def = next((s for s in _pipeline_stages(pipeline) if s.get("name") == deal.stage), None) if pipeline else None
    required = (stage_def or {}).get("required_approval_user_ids") or []
    if user.id not in required:
        raise HTTPException(status_code=403, detail="You're not one of this stage's configured approvers")
    approvals = dict(deal.stage_approvals or {})
    stage_approvals = list(approvals.get(deal.stage, []))
    if any(a["user_id"] == user.id for a in stage_approvals):
        raise HTTPException(status_code=409, detail="You've already approved this")
    stage_approvals.append({"user_id": user.id, "approved_at": datetime.now(timezone.utc).isoformat()})
    approvals[deal.stage] = stage_approvals
    deal.stage_approvals = approvals
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, db.get(CrmContact, deal.contact_id))


@router.get("/deals/{deal_id}/stage-history", response_model=DealStageHistoryOut)
def get_deal_stage_history(deal_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    events = db.scalars(select(DealStageEvent).where(DealStageEvent.deal_id == deal_id).order_by(DealStageEvent.entered_at.asc())).all()
    now = datetime.now(timezone.utc)
    changers = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({e.changed_by_user_id for e in events if e.changed_by_user_id})))}
    return DealStageHistoryOut(events=[
        DealStageEventOut(
            stage=e.stage, entered_at=e.entered_at.isoformat(), exited_at=e.exited_at.isoformat() if e.exited_at else None,
            minutes=round(((e.exited_at or now) - e.entered_at).total_seconds() / 60),
            changed_by_user_id=e.changed_by_user_id, changed_by_name=changers.get(e.changed_by_user_id) if e.changed_by_user_id else None,
        )
        for e in events
    ])


@router.patch("/deals/{deal_id}/owner", response_model=DealOut)
def update_deal_owner(deal_id: str, payload: DealOwnerUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if payload.owner_user_id and payload.owner_user_id != deal.owner_user_id:
        contact = db.get(CrmContact, deal.contact_id)
        notify_user(db, entity.id, payload.owner_user_id, "deal_assigned", "Deal assigned to you", f"{contact.name if contact else 'A deal'} was assigned to you", f"/crm-deals/{deal.id}")
    deal.owner_user_id = payload.owner_user_id
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, db.get(CrmContact, deal.contact_id))


@router.patch("/deals/{deal_id}/notes", response_model=DealOut)
def update_deal_notes(deal_id: str, payload: DealNotesUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal.notes = payload.notes
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, db.get(CrmContact, deal.contact_id))


@router.get("/settings", response_model=CrmSettingsOut)
def get_crm_settings(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Not CRM-gated -- the pipeline stage list is needed to render the lead form even from
    places that already passed their own CRM check (inbox, contact directory), and there's no
    harm in a CRM-inactive entity seeing its own default settings."""
    entity = _resolve_entity(db, user)
    return _settings_out(_get_or_create_settings(db, entity.id))


@router.put("/settings", response_model=CrmSettingsOut)
def update_crm_settings(payload: CrmSettingsUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    settings_row = _get_or_create_settings(db, entity.id)
    settings_row.notify_email = payload.notify_email
    settings_row.notify_sms = payload.notify_sms
    settings_row.notify_whatsapp = payload.notify_whatsapp
    settings_row.brand_color = payload.brand_color
    settings_row.quote_approval_threshold = payload.quote_approval_threshold
    if payload.quote_approver_user_ids is not None:
        settings_row.quote_approver_user_ids = payload.quote_approver_user_ids
    db.commit()
    db.refresh(settings_row)
    return _settings_out(settings_row)


@router.put("/settings/pipeline-stages", response_model=CrmSettingsOut)
def update_pipeline_stages(payload: PipelineStagesUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    stages = [s.strip() for s in payload.stages if s.strip()]
    if not stages:
        raise HTTPException(status_code=422, detail="At least one stage is required")
    if len(stages) != len(set(stages)):
        raise HTTPException(status_code=422, detail="Stage names must be unique")
    settings_row = _get_or_create_settings(db, entity.id)
    settings_row.pipeline_stages = stages
    db.commit()
    db.refresh(settings_row)
    return _settings_out(settings_row)


@router.post("/settings/logo", response_model=CrmSettingsOut)
def upload_crm_logo(logo: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    stored_path, _ = save_upload(logo, "crm_logos")
    settings_row = _get_or_create_settings(db, entity.id)
    settings_row.logo_path = stored_path
    db.commit()
    db.refresh(settings_row)
    return _settings_out(settings_row)


@router.get("/settings/logo")
def get_crm_logo(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    settings_row = db.get(CrmSettings, entity.id)
    if not settings_row or not settings_row.logo_path:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    return FileResponse(settings_row.logo_path)


# --- Pipelines (multiple named pipelines, Phase 1) ---------------------------------------------

@router.get("/pipelines", response_model=list[PipelineOut])
def list_pipelines(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    _get_or_create_default_pipeline(db, entity.id)  # ensures at least one exists
    pipelines = db.scalars(select(Pipeline).where(Pipeline.entity_id == entity.id).order_by(Pipeline.created_at.asc())).all()
    return [_pipeline_out(p) for p in pipelines]


@router.post("/pipelines", response_model=PipelineOut)
def create_pipeline(payload: PipelineCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    pipeline = Pipeline(entity_id=entity.id, name=payload.name.strip(), stages=[s.model_dump() for s in payload.stages])
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    return _pipeline_out(pipeline)


@router.put("/pipelines/{pipeline_id}", response_model=PipelineOut)
def update_pipeline(pipeline_id: str, payload: PipelineCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    pipeline = db.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    pipeline.name = payload.name.strip()
    pipeline.stages = [s.model_dump() for s in payload.stages]
    db.commit()
    db.refresh(pipeline)
    return _pipeline_out(pipeline)


@router.delete("/pipelines/{pipeline_id}")
def delete_pipeline(pipeline_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    pipeline = db.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if db.scalar(select(Deal).where(Deal.pipeline_id == pipeline_id).limit(1)):
        raise HTTPException(status_code=409, detail="Cannot delete a pipeline that has deals in it")
    db.delete(pipeline)
    db.commit()
    return {"deleted": True}


# --- Deal financial fields & status (Phase 1) -----------------------------------------------------

@router.patch("/deals/{deal_id}", response_model=DealOut)
def update_deal(deal_id: str, payload: DealUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if "name" in payload.model_fields_set:
        deal.name = payload.name
    if "value" in payload.model_fields_set:
        deal.value = payload.value
    if "probability" in payload.model_fields_set:
        deal.probability = payload.probability
    if "expected_close_date" in payload.model_fields_set:
        deal.expected_close_date = datetime.fromisoformat(payload.expected_close_date) if payload.expected_close_date else None
    if "next_step" in payload.model_fields_set:
        deal.next_step = payload.next_step
    if "next_step_due_at" in payload.model_fields_set:
        deal.next_step_due_at = datetime.fromisoformat(payload.next_step_due_at) if payload.next_step_due_at else None
    if "custom_fields" in payload.model_fields_set and payload.custom_fields is not None:
        deal.custom_fields = payload.custom_fields
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, db.get(CrmContact, deal.contact_id))


@router.patch("/deals/{deal_id}/status", response_model=DealOut)
def update_deal_status(deal_id: str, payload: DealStatusUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if payload.status == "lost" and not payload.lost_reason:
        raise HTTPException(status_code=422, detail="lost_reason is required when marking a deal lost")
    deal.status = payload.status
    deal.lost_reason = payload.lost_reason if payload.status == "lost" else None
    if payload.status in ("won", "lost") and deal.owner_user_id:
        contact = db.get(CrmContact, deal.contact_id)
        title = "Deal won" if payload.status == "won" else "Deal lost"
        notify_user(db, entity.id, deal.owner_user_id, "deal_status", title, f"{contact.name if contact else 'Your deal'} was marked {payload.status}", f"/crm-deals/{deal.id}")
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, db.get(CrmContact, deal.contact_id))


@router.patch("/deals/{deal_id}/pipeline", response_model=DealOut)
def update_deal_pipeline(deal_id: str, pipeline_id: str, stage: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    pipeline = db.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    stage_names = [s["name"] for s in _pipeline_stages(pipeline)]
    if stage and stage not in stage_names:
        raise HTTPException(status_code=422, detail="Stage not found in the target pipeline")
    _close_open_deal_stage_event(db, deal.id)
    deal.pipeline_id = pipeline.id
    deal.stage = stage or stage_names[0]
    _open_deal_stage_event(db, deal, changed_by_user_id=user.id)
    db.commit()
    db.refresh(deal)
    return _deal_out(deal, db.get(CrmContact, deal.contact_id))


# --- CRM reports (Phase 1) -----------------------------------------------------------------------

@router.get("/reports", response_model=CrmReportsOut)
def get_crm_reports(pipeline_id: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(Deal).where(Deal.entity_id == entity.id)
    if pipeline_id:
        query = query.where(Deal.pipeline_id == pipeline_id)
    deals = db.scalars(query).all()

    open_deals = [d for d in deals if d.status == "open"]
    won_deals = [d for d in deals if d.status == "won"]
    lost_deals = [d for d in deals if d.status == "lost"]

    # Bucketed by (pipeline_id, stage), not stage name alone -- two pipelines can reuse a stage
    # name (e.g. both have "won"), and without the pipeline in the key their totals would get
    # silently merged into one funnel bucket whenever no pipeline_id filter is applied.
    distinct_pipeline_ids = {d.pipeline_id for d in open_deals}
    pipeline_names = {p.id: p.name for p in db.scalars(select(Pipeline).where(Pipeline.id.in_(distinct_pipeline_ids))).all()} if len(distinct_pipeline_ids) > 1 else {}
    stage_totals: dict[tuple[str, str], dict] = {}
    for deal in open_deals:
        row = stage_totals.setdefault((deal.pipeline_id, deal.stage), {"count": 0, "value": 0.0})
        row["count"] += 1
        row["value"] += float(deal.value) if deal.value else 0.0
    funnel = [
        CrmFunnelStage(
            stage=f"{pipeline_names[pid]} - {stage}" if pid in pipeline_names else stage,
            count=row["count"], value=row["value"],
        )
        for (pid, stage), row in stage_totals.items()
    ]

    forecast = sum((float(d.value) if d.value else 0.0) * ((d.probability or 0) / 100) for d in open_deals)
    open_value = sum(float(d.value) if d.value else 0.0 for d in open_deals)
    won_value = sum(float(d.value) if d.value else 0.0 for d in won_deals)
    lost_value = sum(float(d.value) if d.value else 0.0 for d in lost_deals)
    closed_count = len(won_deals) + len(lost_deals)
    win_rate = round(len(won_deals) / closed_count * 100, 1) if closed_count else None

    leads = db.scalars(select(Lead).where(Lead.entity_id == entity.id)).all()
    converted_leads = [l for l in leads if l.status == "converted"]
    lead_conversion_rate = round(len(converted_leads) / len(leads) * 100, 1) if leads else None

    # Last 6 months of lead creation, oldest first -- backs the Reports page's lead-funnel line
    # chart. Months with zero leads are included (not skipped) so the chart's x-axis stays evenly
    # spaced.
    now = datetime.now(timezone.utc)
    month_keys = []
    for i in range(5, -1, -1):
        month_index = now.month - 1 - i
        year = now.year + month_index // 12
        month = month_index % 12 + 1
        month_keys.append(f"{year:04d}-{month:02d}")
    monthly_counts = dict.fromkeys(month_keys, 0)
    for lead in leads:
        key = lead.created_at.strftime("%Y-%m")
        if key in monthly_counts:
            monthly_counts[key] += 1
    monthly_created = [LeadFunnelMonth(month=key, count=monthly_counts[key]) for key in month_keys]

    return CrmReportsOut(
        funnel=funnel, forecast=round(forecast, 2), open_value=round(open_value, 2), won_value=round(won_value, 2),
        lost_value=round(lost_value, 2), open_count=len(open_deals), won_count=len(won_deals), lost_count=len(lost_deals),
        win_rate=win_rate,
        lead_funnel=LeadFunnelOut(created_count=len(leads), converted_count=len(converted_leads), conversion_rate=lead_conversion_rate, monthly_created=monthly_created),
    )


@router.get("/reports/extended", response_model=CrmExtendedReportsOut)
def get_crm_extended_reports(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Sales by employee/product, quotes still awaiting conversion to an invoice ("outstanding"
    -- there's no payment-status field on Invoice, so this is the honest, supportable reading of
    "outstanding payments" given this schema: committed revenue not yet formally invoiced), and
    task/follow-up completion. A second endpoint rather than folding into get_crm_reports above
    since it reads Quote/Task/User, not just Deal."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)

    won_deals = db.scalars(select(Deal).where(Deal.entity_id == entity.id, Deal.status == "won")).all()
    org_users = {u.id: u for u in db.scalars(select(User).where(User.organization_id == user.organization_id)).all()}
    by_employee_totals: dict[str, dict] = {}
    for deal in won_deals:
        if not deal.owner_user_id:
            continue
        row = by_employee_totals.setdefault(deal.owner_user_id, {"count": 0, "value": 0.0})
        row["count"] += 1
        row["value"] += float(deal.value) if deal.value else 0.0
    by_employee = [
        EmployeeSalesRow(user_id=uid, full_name=org_users[uid].full_name if uid in org_users else uid, won_count=row["count"], won_value=round(row["value"], 2))
        for uid, row in sorted(by_employee_totals.items(), key=lambda kv: kv[1]["value"], reverse=True)
    ]

    quotes = db.scalars(select(Quote).where(Quote.entity_id == entity.id)).all()
    by_product_totals: dict[str, dict] = {}
    outstanding_count = 0
    outstanding_value = 0.0
    for quote in quotes:
        if quote.status == "accepted":
            for item in quote.line_items:
                row = by_product_totals.setdefault(item["description"], {"count": 0, "value": 0.0})
                row["count"] += 1
                row["value"] += item["quantity"] * item["unit_price"]
        if quote.status in ("sent", "accepted") and not quote.converted_invoice_id:
            outstanding_count += 1
            outstanding_value += sum(item["quantity"] * item["unit_price"] for item in quote.line_items)
    by_product = [
        ProductSalesRow(description=desc, count=row["count"], value=round(row["value"], 2))
        for desc, row in sorted(by_product_totals.items(), key=lambda kv: kv[1]["value"], reverse=True)
    ]

    tasks = db.scalars(select(Task).where(Task.entity_id == entity.id)).all()
    now = datetime.now(timezone.utc)
    done_tasks = [t for t in tasks if t.done]
    overdue_tasks = [t for t in tasks if not t.done and t.due_at and t.due_at < now]
    done_rate = round(len(done_tasks) / len(tasks) * 100, 1) if tasks else None

    return CrmExtendedReportsOut(
        by_employee=by_employee, by_product=by_product, outstanding_count=outstanding_count,
        outstanding_value=round(outstanding_value, 2),
        follow_up=FollowUpPerformanceOut(total=len(tasks), done=len(done_tasks), overdue=len(overdue_tasks), done_rate=done_rate),
    )


# --- Custom report builder ---------------------------------------------------------------------
# A whitelist, not a query language -- every group_by/measure/filter name below maps to a plain
# Python attribute getter or aggregation function. Rows are fetched with a normal ORM filter, then
# grouped and aggregated in Python (never a dynamic SQL GROUP BY), which is both simple to reason
# about and safe by construction: there's no string ever concatenated into a query.

def _report_owner_label(db: Session, user_id: str | None) -> str:
    if not user_id:
        return "Unassigned"
    user = db.get(User, user_id)
    return user.full_name if user else "Unknown"


REPORT_FIELDS: dict[str, dict] = {
    "deal": {
        "model": Deal,
        "group_by": {
            "stage": lambda db, d: d.stage,
            "status": lambda db, d: d.status,
            "source": lambda db, d: d.source or "Unknown",
            "owner_user_id": lambda db, d: _report_owner_label(db, d.owner_user_id),
            "pipeline_id": lambda db, d: (db.get(Pipeline, d.pipeline_id).name if db.get(Pipeline, d.pipeline_id) else "Unknown"),
        },
        "measure": {
            "count": lambda rows: float(len(rows)),
            "sum_value": lambda rows: round(sum(float(r.value) if r.value else 0.0 for r in rows), 2),
            "avg_probability": lambda rows: round(sum(r.probability or 0 for r in rows) / len(rows), 1) if rows else 0.0,
        },
        "filters": {
            "status": lambda d, v: d.status == v,
            "pipeline_id": lambda d, v: d.pipeline_id == v,
            "owner_user_id": lambda d, v: d.owner_user_id == v,
        },
    },
    "lead": {
        "model": Lead,
        "group_by": {
            "status": lambda db, l: l.status,
            "source": lambda db, l: l.source or "Unknown",
            "owner_user_id": lambda db, l: _report_owner_label(db, l.owner_user_id),
        },
        "measure": {
            "count": lambda rows: float(len(rows)),
            "avg_score": lambda rows: round(sum(r.score or 0 for r in rows) / len(rows), 1) if rows else 0.0,
        },
        "filters": {
            "status": lambda l, v: l.status == v,
            "owner_user_id": lambda l, v: l.owner_user_id == v,
        },
    },
    "task": {
        "model": Task,
        "group_by": {
            "type": lambda db, t: t.type,
            "assigned_user_id": lambda db, t: _report_owner_label(db, t.assigned_user_id),
            "done": lambda db, t: "Done" if t.done else "Open",
        },
        "measure": {
            "count": lambda rows: float(len(rows)),
        },
        "filters": {
            "done": lambda t, v: t.done == (v == "true"),
            "assigned_user_id": lambda t, v: t.assigned_user_id == v,
        },
    },
}


def _run_report(db: Session, entity_id: str, object_type: str, group_by: str, measure: str, filters: dict[str, str]) -> list[ReportRow]:
    spec = REPORT_FIELDS.get(object_type)
    if not spec or group_by not in spec["group_by"] or measure not in spec["measure"]:
        raise HTTPException(status_code=422, detail="Unsupported object/group_by/measure combination")
    for key in filters:
        if key not in spec["filters"]:
            raise HTTPException(status_code=422, detail=f"Unsupported filter: {key}")
    model = spec["model"]
    rows = db.scalars(select(model).where(model.entity_id == entity_id)).all()
    for key, value in filters.items():
        rows = [r for r in rows if spec["filters"][key](r, value)]
    groups: dict[str, list] = {}
    for row in rows:
        label = spec["group_by"][group_by](db, row)
        groups.setdefault(label, []).append(row)
    measure_fn = spec["measure"][measure]
    results = [ReportRow(label=label, value=measure_fn(group_rows)) for label, group_rows in groups.items()]
    return sorted(results, key=lambda r: r.value, reverse=True)[:20]


def _drill_down_row(db: Session, object_type: str, row) -> ReportDrillDownRow:
    if object_type in ("deal", "lead"):
        contact = db.get(CrmContact, row.contact_id)
        label = contact.name if contact and contact.name else (contact.phone if contact else "Unknown")
        sublabel = f"₹{float(row.value):,.0f}" if object_type == "deal" and row.value else row.stage if object_type == "deal" else row.status
        return ReportDrillDownRow(id=row.id, label=label, sublabel=sublabel)
    return ReportDrillDownRow(id=row.id, label=row.title, sublabel=row.type)


def _drill_down(db: Session, entity_id: str, object_type: str, group_by: str, group_value: str, filters: dict[str, str]) -> list[ReportDrillDownRow]:
    spec = REPORT_FIELDS.get(object_type)
    if not spec or group_by not in spec["group_by"]:
        raise HTTPException(status_code=422, detail="Unsupported object/group_by combination")
    for key in filters:
        if key not in spec["filters"]:
            raise HTTPException(status_code=422, detail=f"Unsupported filter: {key}")
    model = spec["model"]
    rows = db.scalars(select(model).where(model.entity_id == entity_id)).all()
    for key, value in filters.items():
        rows = [r for r in rows if spec["filters"][key](r, value)]
    matched = [r for r in rows if spec["group_by"][group_by](db, r) == group_value]
    return [_drill_down_row(db, object_type, r) for r in matched[:50]]


def _saved_report_out(report: SavedReport) -> SavedReportOut:
    return SavedReportOut(
        id=report.id, name=report.name, object_type=report.object_type, group_by=report.group_by,
        measure=report.measure, chart_type=report.chart_type, filters=report.filters or {}, schedule=report.schedule,
        created_at=report.created_at.isoformat(),
    )


@router.post("/reports/run", response_model=ReportRunResult)
def run_report(payload: ReportRunRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rows = _run_report(db, entity.id, payload.object_type, payload.group_by, payload.measure, payload.filters)
    return ReportRunResult(rows=rows)


@router.post("/reports/drill-down", response_model=ReportDrillDownResult)
def drill_down_report(payload: ReportDrillDownRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rows = _drill_down(db, entity.id, payload.object_type, payload.group_by, payload.group_value, payload.filters)
    return ReportDrillDownResult(rows=rows)


@router.get("/reports/saved", response_model=list[SavedReportOut])
def list_saved_reports(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    reports = db.scalars(select(SavedReport).where(SavedReport.entity_id == entity.id, SavedReport.user_id == user.id).order_by(SavedReport.created_at.desc())).all()
    return [_saved_report_out(r) for r in reports]


@router.post("/reports/saved", response_model=SavedReportOut)
def create_saved_report(payload: SavedReportCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    _run_report(db, entity.id, payload.object_type, payload.group_by, payload.measure, payload.filters)  # validates the combination
    report = SavedReport(
        entity_id=entity.id, user_id=user.id, name=payload.name.strip(), object_type=payload.object_type,
        group_by=payload.group_by, measure=payload.measure, chart_type=payload.chart_type, filters=payload.filters,
        schedule=payload.schedule,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _saved_report_out(report)


@router.patch("/reports/saved/{report_id}", response_model=SavedReportOut)
def update_saved_report(report_id: str, payload: SavedReportUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    report = db.get(SavedReport, report_id)
    if not report or report.entity_id != entity.id or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved report not found")
    if "schedule" in payload.model_fields_set:
        report.schedule = payload.schedule
    db.commit()
    db.refresh(report)
    return _saved_report_out(report)


@router.get("/reports/saved/{report_id}/run", response_model=ReportRunResult)
def run_saved_report(report_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    report = db.get(SavedReport, report_id)
    if not report or report.entity_id != entity.id or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved report not found")
    rows = _run_report(db, entity.id, report.object_type, report.group_by, report.measure, report.filters or {})
    return ReportRunResult(rows=rows)


@router.delete("/reports/saved/{report_id}")
def delete_saved_report(report_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    report = db.get(SavedReport, report_id)
    if not report or report.entity_id != entity.id or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved report not found")
    db.delete(report)
    db.commit()
    return {"deleted": True}


def send_due_scheduled_reports() -> None:
    """The scheduled runner (see main.py's lifespan, daily) -- a "weekly" report sends every
    Monday pass, a "monthly" one on the 1st-of-month pass; last_sent_at guards against sending
    twice if the job's misfire-grace-time causes a same-day rerun. Owns its own DB session since
    it runs outside any request context, same pattern as crm_sequences.run_due_steps."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_today = "weekly" if now.weekday() == 0 else "monthly" if now.day == 1 else None
        if not due_today:
            return
        reports = db.scalars(select(SavedReport).where(SavedReport.schedule == due_today)).all()
        for report in reports:
            if report.last_sent_at and report.last_sent_at.date() == now.date():
                continue
            user = db.get(User, report.user_id)
            if not user or not user.email:
                continue
            rows = _run_report(db, report.entity_id, report.object_type, report.group_by, report.measure, report.filters or {})
            table_rows = "".join(f"<tr><td style='padding:4px 12px;'>{r.label}</td><td style='padding:4px 12px;'>{r.value}</td></tr>" for r in rows)
            body = f"<table style='border-collapse:collapse; width:100%;'>{table_rows}</table>" if rows else "<p>No data for this report right now.</p>"
            send_email(db, user.email, f"Report: {report.name}", render_email(report.name, body))
            report.last_sent_at = now
        db.commit()
    except Exception:
        logger.warning("crm: send_due_scheduled_reports failed", exc_info=True)
    finally:
        db.close()


# --- Tasks (Phase 2) -------------------------------------------------------------------------

def _task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id, contact_id=task.contact_id, deal_id=task.deal_id, title=task.title, type=task.type,
        due_at=task.due_at.isoformat() if task.due_at else None, duration_minutes=task.duration_minutes, done=task.done,
        assigned_user_id=task.assigned_user_id, recurrence=task.recurrence, priority=task.priority, outcome=task.outcome,
        created_at=task.created_at.isoformat(),
    )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(contact_id: str | None = None, assigned_user_id: str | None = None, done: bool | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(Task).where(Task.entity_id == entity.id)
    if contact_id:
        query = query.where(Task.contact_id == contact_id)
    # Tasks (including meetings, Task.type="meeting") are private to their assignee by default --
    # only the account owner (enterprise_customer, never granted through a team invite -- see
    # team.py's INVITABLE_ROLES) sees everyone's. A restricted teammate can't work around this by
    # passing a different assigned_user_id; the filter is force-clamped to their own id instead.
    if user.role == UserRole.enterprise_customer.value:
        if assigned_user_id:
            query = query.where(Task.assigned_user_id == assigned_user_id)
    else:
        query = query.where(Task.assigned_user_id == user.id)
    if done is not None:
        query = query.where(Task.done == done)
    tasks = db.scalars(query.order_by(Task.due_at.asc().nulls_last())).all()
    return [_task_out(t) for t in tasks]


@router.post("/tasks", response_model=TaskOut)
def create_task(payload: TaskCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = db.get(CrmContact, payload.contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    task = Task(
        entity_id=entity.id, contact_id=payload.contact_id, deal_id=payload.deal_id, title=payload.title.strip(), type=payload.type,
        due_at=datetime.fromisoformat(payload.due_at) if payload.due_at else None, duration_minutes=payload.duration_minutes,
        assigned_user_id=payload.assigned_user_id, recurrence=payload.recurrence, priority=payload.priority,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if task.assigned_user_id and task.assigned_user_id != user.id:
        notify_user(db, entity.id, task.assigned_user_id, "task_assigned", "Task assigned to you", task.title, "/crm-tasks")
    return _task_out(task)


_RECURRENCE_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    task = db.get(Task, task_id)
    if not task or task.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if "title" in payload.model_fields_set and payload.title:
        task.title = payload.title
    if "type" in payload.model_fields_set and payload.type:
        task.type = payload.type
    if "due_at" in payload.model_fields_set:
        task.due_at = datetime.fromisoformat(payload.due_at) if payload.due_at else None
    if "duration_minutes" in payload.model_fields_set:
        task.duration_minutes = payload.duration_minutes
    if "recurrence" in payload.model_fields_set and payload.recurrence:
        task.recurrence = payload.recurrence
    if "assigned_user_id" in payload.model_fields_set:
        if payload.assigned_user_id and payload.assigned_user_id != task.assigned_user_id and payload.assigned_user_id != user.id:
            notify_user(db, entity.id, payload.assigned_user_id, "task_assigned", "Task assigned to you", task.title, "/crm-tasks")
        task.assigned_user_id = payload.assigned_user_id
    if "deal_id" in payload.model_fields_set:
        task.deal_id = payload.deal_id
    if "priority" in payload.model_fields_set and payload.priority:
        task.priority = payload.priority
    if "outcome" in payload.model_fields_set:
        task.outcome = payload.outcome
    if "done" in payload.model_fields_set and payload.done is not None:
        # A recurring task marked done advances its own due date instead of staying done --
        # "one task, a repeating due date" per the model's own docstring, so it reappears on the
        # follow-up dashboard next cycle instead of needing to be manually recreated.
        if payload.done and task.recurrence != "none" and task.due_at:
            from datetime import timedelta
            task.due_at = task.due_at + timedelta(days=_RECURRENCE_DAYS[task.recurrence])
            task.done = False
        else:
            task.done = payload.done
    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    task = db.get(Task, task_id)
    if not task or task.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"deleted": True}


# --- DPDP Act compliance (Phase 5) --------------------------------------------------------------

@router.put("/contacts/{contact_id}/consent", response_model=ContactOut)
def record_contact_consent(contact_id: str, payload: ConsentUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact.consent_given_at = datetime.now(timezone.utc)
    contact.consent_source = payload.consent_source
    db.commit()
    db.refresh(contact)
    return _contact_out(contact)


@router.get("/contacts/{contact_id}/data-export")
def export_contact_data(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """DPDP Act data-access request support -- everything Textzi holds on this one WhatsApp
    contact, in one JSON bundle: the contact record, their linked CRM contact's leads/deals (if
    this contact has ever been converted), their customer record, and their WhatsApp message
    history. Logged to AccountActivity for the audit trail DPDP expects."""
    entity = _resolve_entity(db, user)
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    crm_contact = db.get(CrmContact, contact.crm_contact_id) if contact.crm_contact_id else None
    leads = db.scalars(select(Lead).where(Lead.contact_id == crm_contact.id)).all() if crm_contact else []
    deals = db.scalars(select(Deal).where(Deal.contact_id == crm_contact.id)).all() if crm_contact else []
    customer = db.get(Customer, contact.customer_id) if contact.customer_id else None
    customer_contact = db.get(CrmContact, customer.contact_id) if customer else None
    conversation = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id))
    messages = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id)).all() if conversation else []
    log_activity(db, user.organization_id, "dpdp_data_export", f"Data export requested for contact {contact_id}.", user_id=user.id, actor_email=user.email)
    db.commit()
    return {
        "contact": _contact_out(contact).model_dump(),
        "crm_contact": _crm_contact_out(crm_contact).model_dump() if crm_contact else None,
        "leads": [_lead_out(lead, crm_contact).model_dump() for lead in leads],
        "deals": [_deal_out(deal, crm_contact).model_dump() for deal in deals],
        "customer": _customer_out(customer, customer_contact).model_dump() if customer else None,
        "messages": [{"direction": m.direction, "body": m.body, "message_type": m.message_type, "created_at": m.created_at.isoformat()} for m in messages if not m.is_private],
    }


@router.delete("/contacts/{contact_id}")
def delete_contact_data(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """DPDP Act right-to-erasure support -- deletes the WhatsApp contact and everything that
    hangs off it: conversation + messages, the linked CRM contact (if any, plus its leads/deals/
    tasks/attachments), and the customer record either side points at. Logged before the rows
    disappear, since there'd be nothing left to log against afterward."""
    entity = _resolve_entity(db, user)
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    log_activity(db, user.organization_id, "dpdp_data_deletion", f"Data deletion requested for contact {contact_id} ({contact.name or contact.wa_id or contact.email}).", user_id=user.id, actor_email=user.email)
    conversation = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id))
    if conversation:
        db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id).delete()
        db.delete(conversation)
    # Delete order matters for FK integrity: Customer.contact_id references crm_contacts.id,
    # Customer.deal_id references deals.id, and Deal.converted_from_lead_id references leads.id
    # -- so Customer -> Deal -> Lead -> CrmContact (Task/Attachment have no further dependents).
    if contact.customer_id:
        db.query(Customer).filter(Customer.id == contact.customer_id).delete()
    crm_contact_id = contact.crm_contact_id
    if crm_contact_id:
        db.query(Deal).filter(Deal.contact_id == crm_contact_id).delete()
        db.query(Lead).filter(Lead.contact_id == crm_contact_id).delete()
        db.query(Task).filter(Task.contact_id == crm_contact_id).delete()
        db.query(Attachment).filter(Attachment.contact_id == crm_contact_id).delete()
    db.commit()
    db.delete(contact)
    db.commit()
    if crm_contact_id:
        db.query(CrmContact).filter(CrmContact.id == crm_contact_id).delete()
        db.commit()
    return {"deleted": True}


# --- Companies -------------------------------------------------------------------------------

def _company_out(db: Session, company: Company) -> CompanyOut:
    contact_count = db.scalar(select(func.count()).select_from(CrmContact).where(CrmContact.company_id == company.id)) or 0
    deals = db.scalars(
        select(Deal).join(CrmContact, CrmContact.id == Deal.contact_id).where(CrmContact.company_id == company.id),
    ).all()
    open_deal_value = sum(float(d.value) if d.value else 0.0 for d in deals if d.status == "open")
    won_deal_value = sum(float(d.value) if d.value else 0.0 for d in deals if d.status == "won")
    open_deal_count = sum(1 for d in deals if d.status == "open")
    return CompanyOut(
        id=company.id, name=company.name, gstin=company.gstin, industry=company.industry, website=company.website,
        notes=company.notes, owner_user_id=company.owner_user_id, account_type=company.account_type,
        parent_company_id=company.parent_company_id, phone=company.phone, address=company.address,
        employee_count=company.employee_count, annual_revenue=float(company.annual_revenue) if company.annual_revenue is not None else None,
        contact_count=contact_count, open_deal_value=round(open_deal_value, 2),
        won_deal_value=round(won_deal_value, 2), open_deal_count=open_deal_count, created_at=company.created_at.isoformat(),
    )


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    companies = db.scalars(select(Company).where(Company.entity_id == entity.id).order_by(Company.name)).all()
    return [_company_out(db, c) for c in companies]


@router.post("/companies", response_model=CompanyOut)
def create_company(payload: CompanyCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    company = Company(
        entity_id=entity.id, name=payload.name.strip(), gstin=payload.gstin, industry=payload.industry, website=payload.website,
        notes=payload.notes, owner_user_id=payload.owner_user_id, account_type=payload.account_type,
        parent_company_id=payload.parent_company_id, phone=payload.phone, address=payload.address,
        employee_count=payload.employee_count, annual_revenue=payload.annual_revenue,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return _company_out(db, company)


@router.get("/companies/{company_id}", response_model=CompanyDetailOut)
def get_company(company_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    company = db.get(Company, company_id)
    if not company or company.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Company not found")
    contacts = db.scalars(select(CrmContact).where(CrmContact.company_id == company_id)).all()
    parent = db.get(Company, company.parent_company_id) if company.parent_company_id else None
    children = db.scalars(select(Company).where(Company.parent_company_id == company_id)).all()
    return CompanyDetailOut(
        company=_company_out(db, company), contacts=[_crm_contact_out(c) for c in contacts],
        parent_company=CompanySummary(id=parent.id, name=parent.name) if parent else None,
        child_companies=[CompanySummary(id=c.id, name=c.name) for c in children],
    )


@router.put("/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: str, payload: CompanyCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    company = db.get(Company, company_id)
    if not company or company.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Company not found")
    if payload.parent_company_id == company_id:
        raise HTTPException(status_code=422, detail="A company cannot be its own parent")
    company.name = payload.name.strip()
    company.gstin = payload.gstin
    company.industry = payload.industry
    company.website = payload.website
    company.notes = payload.notes
    company.owner_user_id = payload.owner_user_id
    company.account_type = payload.account_type
    company.parent_company_id = payload.parent_company_id
    company.phone = payload.phone
    company.address = payload.address
    company.employee_count = payload.employee_count
    company.annual_revenue = payload.annual_revenue
    db.commit()
    db.refresh(company)
    return _company_out(db, company)


@router.delete("/companies/{company_id}")
def delete_company(company_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    company = db.get(Company, company_id)
    if not company or company.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Company not found")
    db.query(CrmContact).filter(CrmContact.company_id == company_id).update({"company_id": None})
    db.query(Company).filter(Company.parent_company_id == company_id).update({"parent_company_id": None})
    db.delete(company)
    db.commit()
    return {"deleted": True}


@router.put("/contacts/{contact_id}/company", response_model=CrmContactOut)
def set_contact_company(contact_id: str, company_id: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = db.get(CrmContact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    if company_id:
        company = db.get(Company, company_id)
        if not company or company.entity_id != entity.id:
            raise HTTPException(status_code=404, detail="Company not found")
    contact.company_id = company_id
    db.commit()
    db.refresh(contact)
    return _crm_contact_out(contact)


@router.get("/companies/{company_id}/contacts", response_model=list[CrmContactOut])
def list_company_contacts(company_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    company = db.get(Company, company_id)
    if not company or company.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Company not found")
    contacts = db.scalars(select(CrmContact).where(CrmContact.company_id == company_id)).all()
    return [_crm_contact_out(c) for c in contacts]


# --- Custom fields (admin-defined, per entity/applies_to) -----------------------------------

def _custom_field_out(field: CustomFieldDefinition) -> CustomFieldDefinitionOut:
    return CustomFieldDefinitionOut(
        id=field.id, applies_to=field.applies_to, name=field.name, field_type=field.field_type,
        options=field.options, required=field.required, position=field.position,
    )


@router.get("/custom-fields", response_model=list[CustomFieldDefinitionOut])
def list_custom_fields(applies_to: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(CustomFieldDefinition).where(CustomFieldDefinition.entity_id == entity.id)
    if applies_to:
        query = query.where(CustomFieldDefinition.applies_to == applies_to)
    fields = db.scalars(query.order_by(CustomFieldDefinition.position, CustomFieldDefinition.created_at)).all()
    return [_custom_field_out(f) for f in fields]


@router.post("/custom-fields", response_model=CustomFieldDefinitionOut)
def create_custom_field(payload: CustomFieldDefinitionCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    name = payload.name.strip()
    existing = db.scalar(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_id == entity.id, CustomFieldDefinition.applies_to == payload.applies_to,
            CustomFieldDefinition.name == name,
        ),
    )
    if existing:
        raise HTTPException(status_code=409, detail="A field with this name already exists on this form")
    max_position = db.scalar(
        select(func.max(CustomFieldDefinition.position)).where(
            CustomFieldDefinition.entity_id == entity.id, CustomFieldDefinition.applies_to == payload.applies_to,
        ),
    ) or 0
    field = CustomFieldDefinition(
        entity_id=entity.id, applies_to=payload.applies_to, name=name, field_type=payload.field_type,
        options=[o.strip() for o in payload.options if o.strip()], required=payload.required, position=max_position + 1,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return _custom_field_out(field)


@router.delete("/custom-fields/{field_id}")
def delete_custom_field(field_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    field = db.get(CustomFieldDefinition, field_id)
    if not field or field.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Custom field not found")
    db.delete(field)
    db.commit()
    return {"deleted": True}


# --- Saved list views (Addendum 12, Phase 3) -- per-user, not shared ------------------------

def _saved_view_out(view: SavedView) -> SavedViewOut:
    return SavedViewOut(id=view.id, applies_to=view.applies_to, name=view.name, filters=view.filters or {}, created_at=view.created_at.isoformat())


@router.get("/saved-views", response_model=list[SavedViewOut])
def list_saved_views(applies_to: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(SavedView).where(SavedView.entity_id == entity.id, SavedView.user_id == user.id)
    if applies_to:
        query = query.where(SavedView.applies_to == applies_to)
    views = db.scalars(query.order_by(SavedView.created_at.asc())).all()
    return [_saved_view_out(v) for v in views]


@router.post("/saved-views", response_model=SavedViewOut)
def create_saved_view(payload: SavedViewCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    view = SavedView(entity_id=entity.id, user_id=user.id, applies_to=payload.applies_to, name=payload.name.strip(), filters=payload.filters or {})
    db.add(view)
    db.commit()
    db.refresh(view)
    return _saved_view_out(view)


@router.delete("/saved-views/{view_id}")
def delete_saved_view(view_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    view = db.get(SavedView, view_id)
    if not view or view.entity_id != entity.id or view.user_id != user.id:
        raise HTTPException(status_code=404, detail="Saved view not found")
    db.delete(view)
    db.commit()
    return {"deleted": True}


# --- Lead scoring (rule-based, Phase "lead scoring") ----------------------------------------

def _scoring_rule_out(rule: ScoringRule) -> ScoringRuleOut:
    return ScoringRuleOut(id=rule.id, name=rule.name, condition_type=rule.condition_type, condition_value=rule.condition_value, points=rule.points, active=rule.active)


@router.get("/scoring-rules", response_model=list[ScoringRuleOut])
def list_scoring_rules(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rules = db.scalars(select(ScoringRule).where(ScoringRule.entity_id == entity.id)).all()
    return [_scoring_rule_out(r) for r in rules]


@router.post("/scoring-rules", response_model=ScoringRuleOut)
def create_scoring_rule(payload: ScoringRuleCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rule = ScoringRule(entity_id=entity.id, name=payload.name.strip(), condition_type=payload.condition_type, condition_value=payload.condition_value, points=payload.points, active=payload.active)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _scoring_rule_out(rule)


@router.patch("/scoring-rules/{rule_id}", response_model=ScoringRuleOut)
def update_scoring_rule(rule_id: str, payload: ScoringRuleUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rule = db.get(ScoringRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Scoring rule not found")
    if "name" in payload.model_fields_set and payload.name:
        rule.name = payload.name.strip()
    if "condition_type" in payload.model_fields_set and payload.condition_type:
        rule.condition_type = payload.condition_type
    if "condition_value" in payload.model_fields_set and payload.condition_value:
        rule.condition_value = payload.condition_value
    if "points" in payload.model_fields_set and payload.points is not None:
        rule.points = payload.points
    if "active" in payload.model_fields_set and payload.active is not None:
        rule.active = payload.active
    db.commit()
    db.refresh(rule)
    return _scoring_rule_out(rule)


@router.delete("/scoring-rules/{rule_id}")
def delete_scoring_rule(rule_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rule = db.get(ScoringRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Scoring rule not found")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


def rescore_lead(db: Session, lead: Lead) -> None:
    """Recomputes Lead.score as a plain point-sum against every active ScoringRule -- called
    after anything that could change a match (label added/removed, custom field set, at creation
    time for source). Explainable and rule-based by design, not a predictive model.

    has_label matching resolves through the lead's linked WhatsApp contact (if any) -- Labels
    stay WABA-owned, so a CRM-native lead with no linked WhatsApp contact simply won't match a
    has_label rule. Only ever mattered for WhatsApp-sourced leads in the first place."""
    from .models import ContactLabel, Label
    rules = db.scalars(select(ScoringRule).where(ScoringRule.entity_id == lead.entity_id, ScoringRule.active.is_(True))).all()
    if not rules:
        lead.score = 0
        return
    waba_contact = _linked_waba_contact(db, lead.entity_id, lead.contact_id)
    contact_label_names = {
        row[0] for row in db.execute(
            select(Label.name).join(ContactLabel, ContactLabel.label_id == Label.id).where(ContactLabel.contact_id == waba_contact.id),
        ).all()
    } if waba_contact else set()
    total = 0
    for rule in rules:
        if rule.condition_type == "has_label" and rule.condition_value in contact_label_names:
            total += rule.points
        elif rule.condition_type == "source" and rule.condition_value == lead.source:
            total += rule.points
        elif rule.condition_type == "custom_field_set" and (lead.custom_fields or {}).get(rule.condition_value):
            total += rule.points
    lead.score = total


@router.post("/leads/{lead_id}/rescore", response_model=LeadOut)
def rescore_lead_endpoint(lead_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    rescore_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(CrmContact, lead.contact_id))


# --- Territories -----------------------------------------------------------------------------

def _territory_out(territory: Territory) -> TerritoryOut:
    return TerritoryOut(
        id=territory.id, name=territory.name, pincodes=territory.pincodes, owner_user_id=territory.owner_user_id,
        parent_territory_id=territory.parent_territory_id,
    )


def _check_territory_parent(db: Session, entity_id: str, territory_id: str | None, parent_id: str | None) -> None:
    """Blocks a territory becoming its own ancestor -- walks up the proposed parent's own chain,
    which also catches indirect cycles (A -> B -> A), not just a direct self-reference."""
    if not parent_id:
        return
    if parent_id == territory_id:
        raise HTTPException(status_code=422, detail="A territory can't be its own parent")
    seen = {territory_id} if territory_id else set()
    current_id = parent_id
    while current_id:
        if current_id in seen:
            raise HTTPException(status_code=422, detail="That would create a loop in the territory hierarchy")
        seen.add(current_id)
        parent = db.get(Territory, current_id)
        if not parent or parent.entity_id != entity_id:
            raise HTTPException(status_code=422, detail="parent_territory_id must belong to your organization")
        current_id = parent.parent_territory_id


@router.get("/territories", response_model=list[TerritoryOut])
def list_territories(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    territories = db.scalars(select(Territory).where(Territory.entity_id == entity.id)).all()
    return [_territory_out(t) for t in territories]


@router.post("/territories", response_model=TerritoryOut)
def create_territory(payload: TerritoryCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    _check_territory_parent(db, entity.id, None, payload.parent_territory_id)
    territory = Territory(
        entity_id=entity.id, name=payload.name.strip(), pincodes=payload.pincodes, owner_user_id=payload.owner_user_id,
        parent_territory_id=payload.parent_territory_id,
    )
    db.add(territory)
    db.commit()
    db.refresh(territory)
    return _territory_out(territory)


@router.patch("/territories/{territory_id}", response_model=TerritoryOut)
def update_territory(territory_id: str, payload: TerritoryUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    territory = db.get(Territory, territory_id)
    if not territory or territory.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Territory not found")
    if "name" in payload.model_fields_set and payload.name:
        territory.name = payload.name.strip()
    if "pincodes" in payload.model_fields_set and payload.pincodes:
        territory.pincodes = payload.pincodes
    if "owner_user_id" in payload.model_fields_set:
        territory.owner_user_id = payload.owner_user_id
    if "parent_territory_id" in payload.model_fields_set:
        _check_territory_parent(db, entity.id, territory.id, payload.parent_territory_id)
        territory.parent_territory_id = payload.parent_territory_id
    db.commit()
    db.refresh(territory)
    return _territory_out(territory)


@router.delete("/territories/{territory_id}")
def delete_territory(territory_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    territory = db.get(Territory, territory_id)
    if not territory or territory.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Territory not found")
    db.query(Territory).filter(Territory.parent_territory_id == territory_id).update({"parent_territory_id": None})
    db.delete(territory)
    db.commit()
    return {"deleted": True}


# --- Sales targets -----------------------------------------------------------------------------

def _sales_target_out(db: Session, target: SalesTarget) -> SalesTargetOut:
    won_deals = db.scalars(
        select(Deal).where(
            Deal.owner_user_id == target.user_id, Deal.status == "won",
            Deal.created_at >= target.period_start, Deal.created_at <= target.period_end,
        ),
    ).all()
    actual = sum(float(d.value) if d.value else 0.0 for d in won_deals)
    return SalesTargetOut(
        id=target.id, user_id=target.user_id, period_start=target.period_start.isoformat(),
        period_end=target.period_end.isoformat(), target_value=float(target.target_value), actual_value=round(actual, 2),
    )


@router.get("/sales-targets", response_model=list[SalesTargetOut])
def list_sales_targets(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    targets = db.scalars(select(SalesTarget).where(SalesTarget.entity_id == entity.id).order_by(SalesTarget.period_start.desc())).all()
    return [_sales_target_out(db, t) for t in targets]


@router.post("/sales-targets", response_model=SalesTargetOut)
def create_sales_target(payload: SalesTargetCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    target = SalesTarget(
        entity_id=entity.id, user_id=payload.user_id, period_start=datetime.fromisoformat(payload.period_start),
        period_end=datetime.fromisoformat(payload.period_end), target_value=payload.target_value,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return _sales_target_out(db, target)


@router.patch("/sales-targets/{target_id}", response_model=SalesTargetOut)
def update_sales_target(target_id: str, payload: SalesTargetUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    target = db.get(SalesTarget, target_id)
    if not target or target.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Sales target not found")
    if "period_start" in payload.model_fields_set and payload.period_start:
        target.period_start = datetime.fromisoformat(payload.period_start)
    if "period_end" in payload.model_fields_set and payload.period_end:
        target.period_end = datetime.fromisoformat(payload.period_end)
    if "target_value" in payload.model_fields_set and payload.target_value is not None:
        target.target_value = payload.target_value
    db.commit()
    db.refresh(target)
    return _sales_target_out(db, target)


@router.delete("/sales-targets/{target_id}")
def delete_sales_target(target_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    target = db.get(SalesTarget, target_id)
    if not target or target.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Sales target not found")
    db.delete(target)
    db.commit()
    return {"deleted": True}


# --- Manager hierarchy -------------------------------------------------------------------------

@router.put("/users/{user_id}/manager")
def set_user_manager(user_id: str, payload: ManagerUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not user.organization_id:
        raise HTTPException(status_code=422, detail="Complete organisation onboarding before setting managers")
    target = db.get(User, user_id)
    if not target or target.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Teammate not found")
    if payload.manager_id:
        manager = db.get(User, payload.manager_id)
        if not manager or manager.organization_id != user.organization_id:
            raise HTTPException(status_code=422, detail="manager_id must belong to your organization")
        if payload.manager_id == user_id:
            raise HTTPException(status_code=422, detail="A teammate can't be their own manager")
    target.manager_id = payload.manager_id
    db.commit()
    return {"id": target.id, "manager_id": target.manager_id}


# --- Notifications -------------------------------------------------------------------------------

def _notification_out(n: Notification) -> NotificationOut:
    return NotificationOut(id=n.id, type=n.type, title=n.title, body=n.body, link=n.link, read=n.read_at is not None, created_at=n.created_at.isoformat())


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    notifications = db.scalars(
        select(Notification).where(Notification.entity_id == entity.id, Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(50),
    ).all()
    return [_notification_out(n) for n in notifications]


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(notification_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not notification.read_at:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return _notification_out(notification)


@router.post("/notifications/read-all")
def mark_all_notifications_read(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    now = datetime.now(timezone.utc)
    unread = db.scalars(
        select(Notification).where(Notification.entity_id == entity.id, Notification.user_id == user.id, Notification.read_at.is_(None)),
    ).all()
    for n in unread:
        n.read_at = now
    db.commit()
    return {"marked_read": len(unread)}


# --- Attachments -------------------------------------------------------------------------------

def _attachment_out(attachment: Attachment) -> AttachmentOut:
    return AttachmentOut(id=attachment.id, contact_id=attachment.contact_id, filename=attachment.filename, uploaded_by_user_id=attachment.uploaded_by_user_id, created_at=attachment.created_at.isoformat())


@router.get("/contacts/{contact_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    attachments = db.scalars(select(Attachment).where(Attachment.contact_id == contact_id, Attachment.entity_id == entity.id)).all()
    return [_attachment_out(a) for a in attachments]


@router.post("/contacts/{contact_id}/attachments", response_model=AttachmentOut)
def upload_attachment(contact_id: str, file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = db.get(CrmContact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    stored_path, _ = save_upload(file, "crm_attachments")
    attachment = Attachment(entity_id=entity.id, contact_id=contact_id, filename=file.filename or "attachment", stored_path=stored_path, uploaded_by_user_id=user.id)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return _attachment_out(attachment)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    attachment = db.get(Attachment, attachment_id)
    if not attachment or attachment.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(attachment.stored_path, filename=attachment.filename)


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    attachment = db.get(Attachment, attachment_id)
    if not attachment or attachment.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    db.delete(attachment)
    db.commit()
    return {"deleted": True}


# --- Web lead-capture form settings (public submit endpoint is in crm_public.py) ---------------

@router.get("/web-form", response_model=WebFormOut)
def get_web_form(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    form = db.get(WebForm, entity.id)
    fields = form.fields if form else ["name", "email", "phone", "message"]
    enabled = form.enabled if form else False
    success_message = form.success_message if form else "Thanks! We'll be in touch shortly."
    target_pipeline_id = form.target_pipeline_id if form else None
    from .config import settings as app_settings
    embed_snippet = f'<iframe src="{app_settings.web_origin}/embed/lead-form/{entity.id}" style="border:0;width:100%;height:480px;"></iframe>'
    return WebFormOut(enabled=enabled, fields=fields, success_message=success_message, target_pipeline_id=target_pipeline_id, embed_snippet=embed_snippet)


@router.put("/web-form", response_model=WebFormOut)
def update_web_form(payload: WebFormUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    form = db.get(WebForm, entity.id)
    if not form:
        form = WebForm(entity_id=entity.id)
        db.add(form)
    form.enabled = payload.enabled
    form.fields = payload.fields
    form.success_message = payload.success_message
    form.target_pipeline_id = payload.target_pipeline_id
    db.commit()
    from .config import settings as app_settings
    embed_snippet = f'<iframe src="{app_settings.web_origin}/embed/lead-form/{entity.id}" style="border:0;width:100%;height:480px;"></iframe>'
    return WebFormOut(enabled=form.enabled, fields=form.fields, success_message=form.success_message, target_pipeline_id=form.target_pipeline_id, embed_snippet=embed_snippet)
