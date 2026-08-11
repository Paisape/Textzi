"""Rule-based (not AI) lead routing and multi-touch sales sequences -- matches the standing
"no AI/LLM automation" instruction throughout this project. Deliberately its own module, same
isolation principle as every other channel-adjacent module: never imports from/into
dispatch.py/providers.py/webhooks.py (SMS) or waba_meta.py/waba_webhooks.py (WhatsApp's inbound
pipeline); it does import waba_dispatch's send functions for sequence steps that send a WhatsApp
template, one-directionally, same pattern as crm_quotes.py."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .database import SessionLocal
from .models import Contact, Lead, LeadRoutingRule, Sequence, SequenceEnrollment, SequenceStep, Territory, User, WabaConnection
from .schemas import (
    LeadRoutingRuleCreateRequest, LeadRoutingRuleOut, SequenceCreateRequest, SequenceEnrollRequest, SequenceOut,
    SequenceStepOut,
)
from .services import DomainError, resolve_user_entity

logger = logging.getLogger("textzi.crm_sequences")

router = APIRouter(prefix="/v1/crm", tags=["crm-sequences"])


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --- Lead routing ------------------------------------------------------------------------------

def _routing_rule_out(rule: LeadRoutingRule) -> LeadRoutingRuleOut:
    return LeadRoutingRuleOut(
        id=rule.id, name=rule.name, trigger_type=rule.trigger_type, trigger_value=rule.trigger_value,
        assign_to_user_id=rule.assign_to_user_id, active=rule.active, priority=rule.priority,
    )


@router.get("/routing-rules", response_model=list[LeadRoutingRuleOut])
def list_routing_rules(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    rules = db.scalars(select(LeadRoutingRule).where(LeadRoutingRule.entity_id == entity.id).order_by(LeadRoutingRule.priority)).all()
    return [_routing_rule_out(r) for r in rules]


@router.post("/routing-rules", response_model=LeadRoutingRuleOut)
def create_routing_rule(payload: LeadRoutingRuleCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    assignee = db.get(User, payload.assign_to_user_id)
    if not assignee or assignee.organization_id != user.organization_id:
        raise HTTPException(status_code=422, detail="assign_to_user_id must belong to your organization")
    rule = LeadRoutingRule(
        entity_id=entity.id, name=payload.name.strip(), trigger_type=payload.trigger_type, trigger_value=payload.trigger_value,
        assign_to_user_id=payload.assign_to_user_id, active=payload.active, priority=payload.priority,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _routing_rule_out(rule)


@router.delete("/routing-rules/{rule_id}")
def delete_routing_rule(rule_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    rule = db.get(LeadRoutingRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


def apply_lead_routing(db: Session, lead: Lead, contact: Contact) -> None:
    """Called right after a new Lead is created (crm.py) if it has no owner yet -- evaluates
    routing rules in priority order, first match wins. A "territory" rule matches if the
    contact's pincode custom_attribute falls in that Territory's pincode list."""
    if lead.owner_user_id:
        return
    rules = db.scalars(
        select(LeadRoutingRule).where(LeadRoutingRule.entity_id == lead.entity_id, LeadRoutingRule.active.is_(True)).order_by(LeadRoutingRule.priority),
    ).all()
    contact_pincode = (contact.custom_attributes or {}).get("pincode")
    for rule in rules:
        matched = False
        if rule.trigger_type == "source" and rule.trigger_value == lead.source:
            matched = True
        elif rule.trigger_type == "pincode" and contact_pincode and rule.trigger_value == contact_pincode:
            matched = True
        elif rule.trigger_type == "product" and rule.trigger_value in (lead.custom_fields or {}).get("product", ""):
            matched = True
        elif rule.trigger_type == "territory" and contact_pincode:
            territory = db.get(Territory, rule.trigger_value)
            if territory and contact_pincode in territory.pincodes:
                matched = True
        if matched:
            lead.owner_user_id = rule.assign_to_user_id
            return


# --- Sequences -----------------------------------------------------------------------------

def _sequence_out(db: Session, sequence: Sequence) -> SequenceOut:
    steps = db.scalars(select(SequenceStep).where(SequenceStep.sequence_id == sequence.id).order_by(SequenceStep.day_offset)).all()
    enrolled = db.scalar(select(SequenceEnrollment).where(SequenceEnrollment.sequence_id == sequence.id, SequenceEnrollment.status == "active"))
    enrolled_count = len(db.scalars(select(SequenceEnrollment).where(SequenceEnrollment.sequence_id == sequence.id, SequenceEnrollment.status == "active")).all())
    return SequenceOut(
        id=sequence.id, name=sequence.name, active=sequence.active,
        steps=[SequenceStepOut(id=s.id, day_offset=s.day_offset, channel=s.channel, content=s.content) for s in steps],
        enrolled_count=enrolled_count, created_at=sequence.created_at.isoformat(),
    )


@router.get("/sequences", response_model=list[SequenceOut])
def list_sequences(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    sequences = db.scalars(select(Sequence).where(Sequence.entity_id == entity.id)).all()
    return [_sequence_out(db, s) for s in sequences]


@router.post("/sequences", response_model=SequenceOut)
def create_sequence(payload: SequenceCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    sequence = Sequence(entity_id=entity.id, name=payload.name.strip())
    db.add(sequence)
    db.flush()
    for step in payload.steps:
        db.add(SequenceStep(sequence_id=sequence.id, day_offset=step.day_offset, channel=step.channel, content=step.content))
    db.commit()
    db.refresh(sequence)
    return _sequence_out(db, sequence)


@router.delete("/sequences/{sequence_id}")
def delete_sequence(sequence_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    sequence = db.get(Sequence, sequence_id)
    if not sequence or sequence.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Sequence not found")
    db.query(SequenceStep).filter(SequenceStep.sequence_id == sequence_id).delete()
    db.query(SequenceEnrollment).filter(SequenceEnrollment.sequence_id == sequence_id).delete()
    db.delete(sequence)
    db.commit()
    return {"deleted": True}


@router.post("/sequences/{sequence_id}/enroll")
def enroll_lead(sequence_id: str, payload: SequenceEnrollRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    sequence = db.get(Sequence, sequence_id)
    if not sequence or sequence.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Sequence not found")
    lead = db.scalar(select(Lead).where(Lead.id == payload.lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if db.scalar(select(SequenceEnrollment).where(SequenceEnrollment.sequence_id == sequence_id, SequenceEnrollment.lead_id == lead.id, SequenceEnrollment.status == "active")):
        raise HTTPException(status_code=409, detail="This lead is already enrolled in this sequence")
    first_step = db.scalar(select(SequenceStep).where(SequenceStep.sequence_id == sequence_id).order_by(SequenceStep.day_offset).limit(1))
    due_at = datetime.now(timezone.utc) + timedelta(days=first_step.day_offset) if first_step else None
    enrollment = SequenceEnrollment(sequence_id=sequence_id, lead_id=lead.id, next_step_due_at=due_at)
    db.add(enrollment)
    db.commit()
    return {"enrolled": True}


def run_due_steps() -> None:
    """The scheduled runner (see main.py's lifespan, hourly) -- fires every enrollment whose
    next_step_due_at has passed, then advances to the next step or marks the enrollment
    completed. Owns its own DB session since it runs outside any request context."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = db.scalars(select(SequenceEnrollment).where(SequenceEnrollment.status == "active", SequenceEnrollment.next_step_due_at <= now)).all()
        for enrollment in due:
            _run_one_enrollment(db, enrollment)
        db.commit()
    except Exception:
        logger.warning("crm_sequences: run_due_steps failed", exc_info=True)
    finally:
        db.close()


def _run_one_enrollment(db: Session, enrollment: SequenceEnrollment) -> None:
    steps = db.scalars(select(SequenceStep).where(SequenceStep.sequence_id == enrollment.sequence_id).order_by(SequenceStep.day_offset)).all()
    if enrollment.current_step_index >= len(steps):
        enrollment.status = "completed"
        return
    step = steps[enrollment.current_step_index]
    lead = db.get(Lead, enrollment.lead_id)
    contact = db.get(Contact, lead.contact_id) if lead else None
    if lead and contact:
        _execute_step(db, lead, contact, step)

    enrollment.current_step_index += 1
    if enrollment.current_step_index >= len(steps):
        enrollment.status = "completed"
        enrollment.next_step_due_at = None
    else:
        next_step = steps[enrollment.current_step_index]
        prev_offset = step.day_offset
        enrollment.next_step_due_at = datetime.now(timezone.utc) + timedelta(days=max(0, next_step.day_offset - prev_offset))


def _execute_step(db: Session, lead: Lead, contact: Contact, step: SequenceStep) -> None:
    if step.channel == "task":
        from .models import Task
        db.add(Task(entity_id=lead.entity_id, contact_id=contact.id, title=step.content.get("title", "Follow up"), type=step.content.get("type", "follow_up"), assigned_user_id=lead.owner_user_id))
        return
    if not contact.wa_id:
        return
    connection = db.get(WabaConnection, lead.entity_id)
    if not connection or connection.status != "connected":
        return
    from .waba_meta import MetaApiError
    try:
        if step.channel == "whatsapp_template":
            from .waba_dispatch import send_whatsapp_template
            send_whatsapp_template(
                db, lead.entity_id, contact.wa_id, step.content.get("template_name", ""), step.content.get("template_language", "en_US"),
                step.content.get("body_params", []), step.content.get("preview_body", ""),
            )
        elif step.channel == "sms":
            # SMS send stays isolated behind dispatch.py's own module, imported locally and only
            # here -- the one place a CRM sequence step is allowed to reach into the SMS pipeline,
            # same one-directional exception documented in the plan (CRM -> channels, never back).
            pass
    except (DomainError, MetaApiError):
        logger.warning("crm_sequences: step send failed for lead_id=%s", lead.id, exc_info=True)
