"""CRM -- the 3rd channel alongside SMS and WhatsApp, gated by channel_active(db, entity_id,
"crm"). Built on the same Contact used by the WhatsApp inbox rather than a parallel contact
table: a Contact with no wa_id is a CRM-only contact. Deliberately its own module, never
importing from or importing into dispatch.py/providers.py/webhooks.py (SMS) or
waba_dispatch.py/waba_meta.py/waba_webhooks.py (WhatsApp's own send/receive pipeline) -- same
isolation principle as every other channel module. It's fine (and intentional) for this module to
read the shared Conversation/Contact inbox tables directly, since those were designed from the
start as the shared-inbox layer, not WhatsApp-pipeline internals."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_user
from .crm_sequences import apply_lead_routing
from .database import get_db
from .models import (
    Attachment, Company, Contact, Conversation, ConversationMessage, CrmSettings, Customer, DEFAULT_CRM_PIPELINE_STAGES, Lead,
    Pipeline, Quote, SalesTarget, ScoringRule, Task, Territory, User, WebForm,
)
from .schemas import (
    AttachmentOut, CompanyCreateRequest, CompanyOut, ConsentUpdateRequest, ContactOut, CrmExtendedReportsOut, CrmReportsOut,
    CrmFunnelStage, CrmSettingsOut, CrmSettingsUpdateRequest, CustomerCreateFromConversationRequest, CustomerOut,
    EmployeeSalesRow, FollowUpPerformanceOut, LeadCreateFromConversationRequest, LeadDealUpdateRequest, LeadNotesUpdateRequest,
    LeadOut, LeadOwnerUpdateRequest, LeadStageUpdateRequest, LeadStatusUpdateRequest, ManagerUpdateRequest,
    MapToCustomerRequest, PipelineCreateRequest, PipelineOut, PipelineStagesUpdateRequest, ProductSalesRow,
    SalesTargetCreateRequest, SalesTargetOut, ScoringRuleCreateRequest, ScoringRuleOut, TaskCreateRequest, TaskOut,
    TaskUpdateRequest, TerritoryCreateRequest, TerritoryOut, WebFormOut, WebFormUpdateRequest,
)
from .services import DomainError, channel_active, log_activity, resolve_user_entity, save_upload

router = APIRouter(prefix="/v1/crm", tags=["crm"])


def _require_crm(db: Session, entity_id: str) -> None:
    if not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to use leads, tickets, and customers")


def _contact_out(contact: Contact) -> ContactOut:
    return ContactOut(
        id=contact.id, wa_id=contact.wa_id, email=contact.email, name=contact.name,
        custom_attributes=contact.custom_attributes or {}, opted_out=contact.opted_out,
        company_id=contact.company_id,
        consent_given_at=contact.consent_given_at.isoformat() if contact.consent_given_at else None,
        consent_source=contact.consent_source, created_at=contact.created_at.isoformat(),
    )


def _lead_out(lead: Lead, contact: Contact) -> LeadOut:
    return LeadOut(
        id=lead.id, contact=_contact_out(contact), pipeline_id=lead.pipeline_id, stage=lead.stage, source=lead.source,
        converted_from_conversation_id=lead.converted_from_conversation_id, owner_user_id=lead.owner_user_id,
        notes=lead.notes, value=float(lead.value) if lead.value is not None else None, probability=lead.probability,
        expected_close_date=lead.expected_close_date.isoformat() if lead.expected_close_date else None,
        status=lead.status, lost_reason=lead.lost_reason, custom_fields=lead.custom_fields or {}, score=lead.score,
        created_at=lead.created_at.isoformat(),
    )


def _customer_out(customer: Customer, contact: Contact) -> CustomerOut:
    return CustomerOut(
        id=customer.id, contact=_contact_out(contact), lead_id=customer.lead_id,
        converted_from_conversation_id=customer.converted_from_conversation_id, owner_user_id=customer.owner_user_id,
        notes=customer.notes, created_at=customer.created_at.isoformat(),
    )


def _get_or_create_default_pipeline(db: Session, entity_id: str) -> Pipeline:
    """Migrates CrmSettings.pipeline_stages (the old single-pipeline source of truth) into a
    "Default" Pipeline row the first time it's needed, so existing leads/settings keep working
    unchanged under the new multi-pipeline model."""
    pipeline = db.scalar(select(Pipeline).where(Pipeline.entity_id == entity_id).order_by(Pipeline.created_at.asc()))
    if pipeline:
        return pipeline
    settings_row = db.get(CrmSettings, entity_id)
    stages = settings_row.pipeline_stages if settings_row and settings_row.pipeline_stages else list(DEFAULT_CRM_PIPELINE_STAGES)
    pipeline = Pipeline(entity_id=entity_id, name="Default", stages=stages)
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    return pipeline


def _pipeline_out(pipeline: Pipeline) -> PipelineOut:
    return PipelineOut(id=pipeline.id, name=pipeline.name, stages=pipeline.stages)


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
    )


def _get_owned_contact(db: Session, entity_id: str, contact_id: str) -> Contact:
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.get("/status")
def get_crm_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Lightweight, no-422 status check -- lets the frontend nav decide whether to show the CRM
    menu group without having to interpret a failed /leads call as "not subscribed"."""
    entity = _resolve_entity(db, user)
    return {"active": channel_active(db, entity.id, "crm")}


@router.get("/leads", response_model=list[LeadOut])
def list_leads(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    leads = db.scalars(select(Lead).where(Lead.entity_id == entity.id).order_by(Lead.created_at.desc())).all()
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_([lead.contact_id for lead in leads]))).all()} if leads else {}
    return [_lead_out(lead, contacts[lead.contact_id]) for lead in leads]


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    customers = db.scalars(select(Customer).where(Customer.entity_id == entity.id).order_by(Customer.created_at.desc())).all()
    contacts = {c.id: c for c in db.scalars(select(Contact).where(Contact.id.in_([customer.contact_id for customer in customers]))).all()} if customers else {}
    return [_customer_out(customer, contacts[customer.contact_id]) for customer in customers]


@router.post("/conversations/{conversation_id}/convert-to-lead", response_model=LeadOut)
def convert_conversation_to_lead(
    conversation_id: str, payload: LeadCreateFromConversationRequest = LeadCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """stage/owner/notes come from the agent's own right-panel form -- filled in live during the
    chat rather than defaulted blind, since a lead is worth more with real context captured while
    the customer is actually available to ask."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    existing = db.scalar(select(Lead).where(Lead.converted_from_conversation_id == conversation_id))
    if existing:
        raise HTTPException(status_code=409, detail="This conversation was already converted to a lead")
    lead = Lead(
        entity_id=entity.id, contact_id=contact.id, source="whatsapp_conversation", converted_from_conversation_id=conversation_id,
        stage=payload.stage, owner_user_id=payload.owner_user_id, notes=payload.notes,
    )
    db.add(lead)
    db.flush()
    apply_lead_routing(db, lead, contact)
    rescore_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, contact)


@router.post("/conversations/{conversation_id}/convert-to-customer", response_model=CustomerOut)
def convert_conversation_to_customer(
    conversation_id: str, payload: CustomerCreateFromConversationRequest = CustomerCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """Direct conversation -> Customer, independent of the Lead pipeline -- for an existing
    customer messaging in where there's no real sales process to track."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    conversation, contact = _get_owned_conversation(db, entity.id, conversation_id)
    existing = db.scalar(select(Customer).where(Customer.converted_from_conversation_id == conversation_id))
    if existing:
        raise HTTPException(status_code=409, detail="This conversation was already converted to a customer")
    customer = Customer(
        entity_id=entity.id, contact_id=contact.id, converted_from_conversation_id=conversation_id,
        owner_user_id=payload.owner_user_id, notes=payload.notes,
    )
    db.add(customer)
    db.flush()
    contact.customer_id = customer.id
    db.commit()
    db.refresh(customer)
    return _customer_out(customer, contact)


@router.post("/leads/{lead_id}/convert-to-customer", response_model=CustomerOut)
def convert_lead_to_customer(lead_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    existing = db.scalar(select(Customer).where(Customer.lead_id == lead_id))
    if existing:
        raise HTTPException(status_code=409, detail="This lead was already converted to a customer")
    contact = db.get(Contact, lead.contact_id)
    customer = Customer(
        entity_id=entity.id, contact_id=lead.contact_id, lead_id=lead.id,
        converted_from_conversation_id=lead.converted_from_conversation_id, owner_user_id=lead.owner_user_id, notes=lead.notes,
    )
    db.add(customer)
    db.flush()
    contact.customer_id = customer.id
    db.commit()
    db.refresh(customer)
    return _customer_out(customer, contact)


@router.post("/contacts/{contact_id}/convert-to-lead", response_model=LeadOut)
def convert_contact_to_lead(
    contact_id: str, payload: LeadCreateFromConversationRequest = LeadCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """Same as the conversation-based conversion, but reachable from the contacts directory
    where an agent may want to create a lead without having an open conversation selected.
    Duplicate-lead detection only blocks on an existing OPEN lead -- a contact whose earlier lead
    already closed (won or lost) can legitimately become a new lead (e.g. a renewal opportunity)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _get_owned_contact(db, entity.id, contact_id)
    existing = db.scalar(select(Lead).where(Lead.contact_id == contact_id, Lead.entity_id == entity.id, Lead.status == "open"))
    if existing:
        raise HTTPException(status_code=409, detail=f"This contact already has an open lead (created {existing.created_at.date().isoformat()}) -- close it before creating a new one")
    lead = Lead(entity_id=entity.id, contact_id=contact.id, source="manual", stage=payload.stage, owner_user_id=payload.owner_user_id, notes=payload.notes)
    db.add(lead)
    db.flush()
    apply_lead_routing(db, lead, contact)
    rescore_lead(db, lead)
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, contact)


@router.post("/contacts/{contact_id}/convert-to-customer", response_model=CustomerOut)
def convert_contact_to_customer(
    contact_id: str, payload: CustomerCreateFromConversationRequest = CustomerCreateFromConversationRequest(),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = _get_owned_contact(db, entity.id, contact_id)
    if contact.customer_id:
        raise HTTPException(status_code=409, detail="This contact is already linked to a customer")
    customer = Customer(entity_id=entity.id, contact_id=contact.id, owner_user_id=payload.owner_user_id, notes=payload.notes)
    db.add(customer)
    db.flush()
    contact.customer_id = customer.id
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


@router.patch("/leads/{lead_id}/stage", response_model=LeadOut)
def update_lead_stage(lead_id: str, payload: LeadStageUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.stage = payload.stage
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(Contact, lead.contact_id))


@router.patch("/leads/{lead_id}/owner", response_model=LeadOut)
def update_lead_owner(lead_id: str, payload: LeadOwnerUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.owner_user_id = payload.owner_user_id
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(Contact, lead.contact_id))


@router.patch("/leads/{lead_id}/notes", response_model=LeadOut)
def update_lead_notes(lead_id: str, payload: LeadNotesUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.notes = payload.notes
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(Contact, lead.contact_id))


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
    pipeline = Pipeline(entity_id=entity.id, name=payload.name.strip(), stages=payload.stages)
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
    pipeline.stages = payload.stages
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
    if db.scalar(select(Lead).where(Lead.pipeline_id == pipeline_id).limit(1)):
        raise HTTPException(status_code=409, detail="Cannot delete a pipeline that has leads in it")
    db.delete(pipeline)
    db.commit()
    return {"deleted": True}


# --- Lead deal fields & status (Phase 1) --------------------------------------------------------

@router.patch("/leads/{lead_id}/deal", response_model=LeadOut)
def update_lead_deal(lead_id: str, payload: LeadDealUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if "value" in payload.model_fields_set:
        lead.value = payload.value
    if "probability" in payload.model_fields_set:
        lead.probability = payload.probability
    if "expected_close_date" in payload.model_fields_set:
        lead.expected_close_date = datetime.fromisoformat(payload.expected_close_date) if payload.expected_close_date else None
    if "custom_fields" in payload.model_fields_set and payload.custom_fields is not None:
        lead.custom_fields = payload.custom_fields
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(Contact, lead.contact_id))


@router.patch("/leads/{lead_id}/status", response_model=LeadOut)
def update_lead_status(lead_id: str, payload: LeadStatusUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if payload.status == "lost" and not payload.lost_reason:
        raise HTTPException(status_code=422, detail="lost_reason is required when marking a lead lost")
    lead.status = payload.status
    lead.lost_reason = payload.lost_reason if payload.status == "lost" else None
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(Contact, lead.contact_id))


@router.patch("/leads/{lead_id}/pipeline", response_model=LeadOut)
def update_lead_pipeline(lead_id: str, pipeline_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    pipeline = db.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    lead.pipeline_id = pipeline.id
    lead.stage = pipeline.stages[0]
    db.commit()
    db.refresh(lead)
    return _lead_out(lead, db.get(Contact, lead.contact_id))


# --- CRM reports (Phase 1) -----------------------------------------------------------------------

@router.get("/reports", response_model=CrmReportsOut)
def get_crm_reports(pipeline_id: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(Lead).where(Lead.entity_id == entity.id)
    if pipeline_id:
        query = query.where(Lead.pipeline_id == pipeline_id)
    leads = db.scalars(query).all()

    open_leads = [l for l in leads if l.status == "open"]
    won_leads = [l for l in leads if l.status == "won"]
    lost_leads = [l for l in leads if l.status == "lost"]

    stage_totals: dict[str, dict] = {}
    for lead in open_leads:
        row = stage_totals.setdefault(lead.stage, {"count": 0, "value": 0.0})
        row["count"] += 1
        row["value"] += float(lead.value) if lead.value else 0.0
    funnel = [CrmFunnelStage(stage=stage, count=row["count"], value=row["value"]) for stage, row in stage_totals.items()]

    forecast = sum((float(l.value) if l.value else 0.0) * ((l.probability or 0) / 100) for l in open_leads)
    open_value = sum(float(l.value) if l.value else 0.0 for l in open_leads)
    won_value = sum(float(l.value) if l.value else 0.0 for l in won_leads)
    lost_value = sum(float(l.value) if l.value else 0.0 for l in lost_leads)
    closed_count = len(won_leads) + len(lost_leads)
    win_rate = round(len(won_leads) / closed_count * 100, 1) if closed_count else None

    return CrmReportsOut(
        funnel=funnel, forecast=round(forecast, 2), open_value=round(open_value, 2), won_value=round(won_value, 2),
        lost_value=round(lost_value, 2), open_count=len(open_leads), won_count=len(won_leads), lost_count=len(lost_leads),
        win_rate=win_rate,
    )


@router.get("/reports/extended", response_model=CrmExtendedReportsOut)
def get_crm_extended_reports(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Sales by employee/product, quotes still awaiting conversion to an invoice ("outstanding"
    -- there's no payment-status field on Invoice, so this is the honest, supportable reading of
    "outstanding payments" given this schema: committed revenue not yet formally invoiced), and
    task/follow-up completion. A second endpoint rather than folding into get_crm_reports above
    since it reads Quote/Task/User, not just Lead."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)

    won_leads = db.scalars(select(Lead).where(Lead.entity_id == entity.id, Lead.status == "won")).all()
    org_users = {u.id: u for u in db.scalars(select(User).where(User.organization_id == user.organization_id)).all()}
    by_employee_totals: dict[str, dict] = {}
    for lead in won_leads:
        if not lead.owner_user_id:
            continue
        row = by_employee_totals.setdefault(lead.owner_user_id, {"count": 0, "value": 0.0})
        row["count"] += 1
        row["value"] += float(lead.value) if lead.value else 0.0
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


# --- Tasks (Phase 2) -------------------------------------------------------------------------

def _task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id, contact_id=task.contact_id, title=task.title, type=task.type,
        due_at=task.due_at.isoformat() if task.due_at else None, done=task.done,
        assigned_user_id=task.assigned_user_id, recurrence=task.recurrence, created_at=task.created_at.isoformat(),
    )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(contact_id: str | None = None, assigned_user_id: str | None = None, done: bool | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(Task).where(Task.entity_id == entity.id)
    if contact_id:
        query = query.where(Task.contact_id == contact_id)
    if assigned_user_id:
        query = query.where(Task.assigned_user_id == assigned_user_id)
    if done is not None:
        query = query.where(Task.done == done)
    tasks = db.scalars(query.order_by(Task.due_at.asc().nulls_last())).all()
    return [_task_out(t) for t in tasks]


@router.post("/tasks", response_model=TaskOut)
def create_task(payload: TaskCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = db.get(Contact, payload.contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    task = Task(
        entity_id=entity.id, contact_id=payload.contact_id, title=payload.title.strip(), type=payload.type,
        due_at=datetime.fromisoformat(payload.due_at) if payload.due_at else None, assigned_user_id=payload.assigned_user_id,
        recurrence=payload.recurrence,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
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
    if "recurrence" in payload.model_fields_set and payload.recurrence:
        task.recurrence = payload.recurrence
    if "assigned_user_id" in payload.model_fields_set:
        task.assigned_user_id = payload.assigned_user_id
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
    """DPDP Act data-access request support -- everything Textzi holds on this one contact, in
    one JSON bundle: the contact record, their leads/customer record, and their WhatsApp message
    history. Logged to AccountActivity for the audit trail DPDP expects."""
    entity = _resolve_entity(db, user)
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    leads = db.scalars(select(Lead).where(Lead.contact_id == contact_id)).all()
    customer = db.get(Customer, contact.customer_id) if contact.customer_id else None
    conversation = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id))
    messages = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id)).all() if conversation else []
    log_activity(db, user.organization_id, "dpdp_data_export", f"Data export requested for contact {contact_id}.", user_id=user.id, actor_email=user.email)
    db.commit()
    return {
        "contact": _contact_out(contact).model_dump(),
        "leads": [_lead_out(lead, contact).model_dump() for lead in leads],
        "customer": _customer_out(customer, contact).model_dump() if customer else None,
        "messages": [{"direction": m.direction, "body": m.body, "message_type": m.message_type, "created_at": m.created_at.isoformat()} for m in messages if not m.is_private],
    }


@router.delete("/contacts/{contact_id}")
def delete_contact_data(contact_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """DPDP Act right-to-erasure support -- deletes the contact and everything that hangs off it
    (leads, customer link, conversation + messages). Logged before the row disappears, since
    there'd be nothing left to log against afterward."""
    entity = _resolve_entity(db, user)
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    log_activity(db, user.organization_id, "dpdp_data_deletion", f"Data deletion requested for contact {contact_id} ({contact.name or contact.wa_id or contact.email}).", user_id=user.id, actor_email=user.email)
    conversation = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id))
    if conversation:
        db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id).delete()
        db.delete(conversation)
    db.query(Lead).filter(Lead.contact_id == contact_id).delete()
    if contact.customer_id:
        db.query(Customer).filter(Customer.id == contact.customer_id).delete()
    db.commit()
    db.delete(contact)
    db.commit()
    return {"deleted": True}


# --- Companies -------------------------------------------------------------------------------

def _company_out(db: Session, company: Company) -> CompanyOut:
    contact_count = db.scalar(select(func.count()).select_from(Contact).where(Contact.company_id == company.id)) or 0
    return CompanyOut(
        id=company.id, name=company.name, gstin=company.gstin, industry=company.industry, website=company.website,
        notes=company.notes, contact_count=contact_count, created_at=company.created_at.isoformat(),
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
    company = Company(entity_id=entity.id, name=payload.name.strip(), gstin=payload.gstin, industry=payload.industry, website=payload.website, notes=payload.notes)
    db.add(company)
    db.commit()
    db.refresh(company)
    return _company_out(db, company)


@router.put("/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: str, payload: CompanyCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    company = db.get(Company, company_id)
    if not company or company.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Company not found")
    company.name = payload.name.strip()
    company.gstin = payload.gstin
    company.industry = payload.industry
    company.website = payload.website
    company.notes = payload.notes
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
    db.query(Contact).filter(Contact.company_id == company_id).update({"company_id": None})
    db.delete(company)
    db.commit()
    return {"deleted": True}


@router.put("/contacts/{contact_id}/company", response_model=ContactOut)
def set_contact_company(contact_id: str, company_id: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    contact = db.get(Contact, contact_id)
    if not contact or contact.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    if company_id:
        company = db.get(Company, company_id)
        if not company or company.entity_id != entity.id:
            raise HTTPException(status_code=404, detail="Company not found")
    contact.company_id = company_id
    db.commit()
    db.refresh(contact)
    return _contact_out(contact)


@router.get("/companies/{company_id}/contacts", response_model=list[ContactOut])
def list_company_contacts(company_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    company = db.get(Company, company_id)
    if not company or company.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Company not found")
    contacts = db.scalars(select(Contact).where(Contact.company_id == company_id)).all()
    return [_contact_out(c) for c in contacts]


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
    time for source). Explainable and rule-based by design, not a predictive model."""
    from .models import ContactLabel, Label
    rules = db.scalars(select(ScoringRule).where(ScoringRule.entity_id == lead.entity_id, ScoringRule.active.is_(True))).all()
    if not rules:
        lead.score = 0
        return
    contact_label_names = {
        row[0] for row in db.execute(
            select(Label.name).join(ContactLabel, ContactLabel.label_id == Label.id).where(ContactLabel.contact_id == lead.contact_id),
        ).all()
    }
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
    return _lead_out(lead, db.get(Contact, lead.contact_id))


# --- Territories -----------------------------------------------------------------------------

def _territory_out(territory: Territory) -> TerritoryOut:
    return TerritoryOut(id=territory.id, name=territory.name, pincodes=territory.pincodes, owner_user_id=territory.owner_user_id)


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
    territory = Territory(entity_id=entity.id, name=payload.name.strip(), pincodes=payload.pincodes, owner_user_id=payload.owner_user_id)
    db.add(territory)
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
    db.delete(territory)
    db.commit()
    return {"deleted": True}


# --- Sales targets -----------------------------------------------------------------------------

def _sales_target_out(db: Session, target: SalesTarget) -> SalesTargetOut:
    won_leads = db.scalars(
        select(Lead).where(
            Lead.owner_user_id == target.user_id, Lead.status == "won",
            Lead.created_at >= target.period_start, Lead.created_at <= target.period_end,
        ),
    ).all()
    actual = sum(float(l.value) if l.value else 0.0 for l in won_leads)
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
    contact = db.get(Contact, contact_id)
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
