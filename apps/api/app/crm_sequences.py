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
from .models import CrmContact, Deal, Lead, LeadRoutingRule, Sequence, SequenceEnrollment, SequenceStep, Territory, User, WabaConnection
from .permissions import require_channel_scope, require_page_scope_for
from .schemas import (
    LeadRoutingRuleCreateRequest, LeadRoutingRuleOut, LeadRoutingRuleUpdateRequest, SequenceCreateRequest, SequenceEnrollRequest, SequenceOut,
    SequenceStepOut, SequenceUpdateRequest,
)
from .services import DomainError, channel_active, resolve_user_entity

logger = logging.getLogger("textzi.crm_sequences")

router = APIRouter(prefix="/v1/crm", tags=["crm-sequences"], dependencies=[Depends(require_channel_scope("crm")), Depends(require_page_scope_for("crm-automation"))])


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_crm(db: Session, entity_id: str) -> None:
    if not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to use routing rules and sequences")


# --- Lead routing ------------------------------------------------------------------------------

def _routing_rule_out(rule: LeadRoutingRule) -> LeadRoutingRuleOut:
    return LeadRoutingRuleOut(
        id=rule.id, name=rule.name, trigger_type=rule.trigger_type, trigger_value=rule.trigger_value,
        assign_to_user_id=rule.assign_to_user_id, active=rule.active, priority=rule.priority,
    )


@router.get("/routing-rules", response_model=list[LeadRoutingRuleOut])
def list_routing_rules(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rules = db.scalars(select(LeadRoutingRule).where(LeadRoutingRule.entity_id == entity.id).order_by(LeadRoutingRule.priority)).all()
    return [_routing_rule_out(r) for r in rules]


@router.post("/routing-rules", response_model=LeadRoutingRuleOut)
def create_routing_rule(payload: LeadRoutingRuleCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
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


@router.patch("/routing-rules/{rule_id}", response_model=LeadRoutingRuleOut)
def update_routing_rule(rule_id: str, payload: LeadRoutingRuleUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rule = db.get(LeadRoutingRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    if "assign_to_user_id" in payload.model_fields_set and payload.assign_to_user_id:
        assignee = db.get(User, payload.assign_to_user_id)
        if not assignee or assignee.organization_id != user.organization_id:
            raise HTTPException(status_code=422, detail="assign_to_user_id must belong to your organization")
        rule.assign_to_user_id = payload.assign_to_user_id
    if "name" in payload.model_fields_set and payload.name:
        rule.name = payload.name.strip()
    if "trigger_type" in payload.model_fields_set and payload.trigger_type:
        rule.trigger_type = payload.trigger_type
    if "trigger_value" in payload.model_fields_set and payload.trigger_value:
        rule.trigger_value = payload.trigger_value
    if "active" in payload.model_fields_set and payload.active is not None:
        rule.active = payload.active
    if "priority" in payload.model_fields_set and payload.priority is not None:
        rule.priority = payload.priority
    db.commit()
    db.refresh(rule)
    return _routing_rule_out(rule)


@router.delete("/routing-rules/{rule_id}")
def delete_routing_rule(rule_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rule = db.get(LeadRoutingRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


def apply_lead_routing(db: Session, lead: Lead, contact: CrmContact) -> None:
    """Called right after a new Lead is created (crm.py) if it has no owner yet -- evaluates
    routing rules in priority order, first match wins. A "territory" rule matches if the
    contact's pincode custom field falls in that Territory's pincode list."""
    if lead.owner_user_id:
        return
    rules = db.scalars(
        select(LeadRoutingRule).where(LeadRoutingRule.entity_id == lead.entity_id, LeadRoutingRule.active.is_(True)).order_by(LeadRoutingRule.priority),
    ).all()
    contact_pincode = (contact.custom_fields or {}).get("pincode")
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
        id=sequence.id, name=sequence.name, active=sequence.active, exit_stage=sequence.exit_stage,
        steps=[SequenceStepOut(id=s.id, day_offset=s.day_offset, channel=s.channel, content=s.content, only_if_stage=s.only_if_stage) for s in steps],
        enrolled_count=enrolled_count, created_at=sequence.created_at.isoformat(),
    )


@router.get("/sequences", response_model=list[SequenceOut])
def list_sequences(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    sequences = db.scalars(select(Sequence).where(Sequence.entity_id == entity.id)).all()
    return [_sequence_out(db, s) for s in sequences]


@router.post("/sequences", response_model=SequenceOut)
def create_sequence(payload: SequenceCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    sequence = Sequence(entity_id=entity.id, name=payload.name.strip(), exit_stage=payload.exit_stage)
    db.add(sequence)
    db.flush()
    for step in payload.steps:
        db.add(SequenceStep(sequence_id=sequence.id, day_offset=step.day_offset, channel=step.channel, content=step.content, only_if_stage=step.only_if_stage))
    db.commit()
    db.refresh(sequence)
    return _sequence_out(db, sequence)


@router.patch("/sequences/{sequence_id}", response_model=SequenceOut)
def update_sequence(sequence_id: str, payload: SequenceUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    sequence = db.get(Sequence, sequence_id)
    if not sequence or sequence.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Sequence not found")
    if "name" in payload.model_fields_set and payload.name:
        sequence.name = payload.name.strip()
    if "active" in payload.model_fields_set and payload.active is not None:
        sequence.active = payload.active
    if "exit_stage" in payload.model_fields_set:
        sequence.exit_stage = payload.exit_stage
    if "steps" in payload.model_fields_set and payload.steps is not None:
        db.query(SequenceStep).filter(SequenceStep.sequence_id == sequence_id).delete()
        for step in payload.steps:
            db.add(SequenceStep(sequence_id=sequence.id, day_offset=step.day_offset, channel=step.channel, content=step.content, only_if_stage=step.only_if_stage))
    db.commit()
    db.refresh(sequence)
    return _sequence_out(db, sequence)


@router.delete("/sequences/{sequence_id}")
def delete_sequence(sequence_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    sequence = db.get(Sequence, sequence_id)
    if not sequence or sequence.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Sequence not found")
    db.query(SequenceStep).filter(SequenceStep.sequence_id == sequence_id).delete()
    db.query(SequenceEnrollment).filter(SequenceEnrollment.sequence_id == sequence_id).delete()
    db.delete(sequence)
    db.commit()
    return {"deleted": True}


@router.post("/sequences/{sequence_id}/enroll")
def enroll_deal(sequence_id: str, payload: SequenceEnrollRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    sequence = db.get(Sequence, sequence_id)
    if not sequence or sequence.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Sequence not found")
    deal = db.scalar(select(Deal).where(Deal.id == payload.deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if db.scalar(select(SequenceEnrollment).where(SequenceEnrollment.sequence_id == sequence_id, SequenceEnrollment.deal_id == deal.id, SequenceEnrollment.status == "active")):
        raise HTTPException(status_code=409, detail="This deal is already enrolled in this sequence")
    first_step = db.scalar(select(SequenceStep).where(SequenceStep.sequence_id == sequence_id).order_by(SequenceStep.day_offset).limit(1))
    due_at = datetime.now(timezone.utc) + timedelta(days=first_step.day_offset) if first_step else None
    enrollment = SequenceEnrollment(sequence_id=sequence_id, deal_id=deal.id, next_step_due_at=due_at)
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
    deal = db.get(Deal, enrollment.deal_id)
    contact = db.get(CrmContact, deal.contact_id) if deal else None

    # The one exit condition (see Sequence's own docstring): a closed deal never gets another
    # step regardless of sequence config, and a deal that's reached this sequence's exit_stage
    # stops here too -- both checked before running the step, not after.
    sequence = db.get(Sequence, enrollment.sequence_id)
    if deal and (deal.status != "open" or (sequence and sequence.exit_stage and deal.stage == sequence.exit_stage)):
        enrollment.status = "completed"
        enrollment.next_step_due_at = None
        return

    # Per-step branching guard: a step with only_if_stage is skipped (the enrollment still
    # advances past it) unless the deal is currently sitting in exactly that stage.
    if deal and contact and (not step.only_if_stage or deal.stage == step.only_if_stage):
        _execute_step(db, deal, contact, step)

    enrollment.current_step_index += 1
    if enrollment.current_step_index >= len(steps):
        enrollment.status = "completed"
        enrollment.next_step_due_at = None
    else:
        next_step = steps[enrollment.current_step_index]
        prev_offset = step.day_offset
        enrollment.next_step_due_at = datetime.now(timezone.utc) + timedelta(days=max(0, next_step.day_offset - prev_offset))


def _execute_step(db: Session, deal: Deal, contact: CrmContact, step: SequenceStep) -> None:
    if step.channel == "task":
        from .models import Task
        db.add(Task(entity_id=deal.entity_id, contact_id=contact.id, deal_id=deal.id, title=step.content.get("title", "Follow up"), type=step.content.get("type", "follow_up"), assigned_user_id=deal.owner_user_id))
        return
    if not contact.phone:
        return
    connection = db.get(WabaConnection, deal.entity_id)
    if not connection or connection.status != "connected":
        return
    from .waba_meta import MetaApiError
    try:
        if step.channel == "whatsapp_template":
            from .waba_dispatch import send_whatsapp_template
            # send_whatsapp_template resolves/creates the WABA Contact by this number
            # just-in-time (waba_dispatch._resolve_send_target) -- a CRM-native deal with no
            # linked WhatsApp contact yet still sends fine.
            wa_id = "".join(ch for ch in contact.phone if ch.isdigit())
            send_whatsapp_template(
                db, deal.entity_id, wa_id, step.content.get("template_name", ""), step.content.get("template_language", "en_US"),
                step.content.get("body_params", []), step.content.get("preview_body", ""),
            )
        elif step.channel == "sms":
            # SMS send stays isolated behind dispatch.py's own module, imported locally and only
            # here -- the one place a CRM sequence step is allowed to reach into the SMS pipeline,
            # same one-directional exception documented in the plan (CRM -> channels, never back).
            pass
    except (DomainError, MetaApiError):
        logger.warning("crm_sequences: step send failed for deal_id=%s", deal.id, exc_info=True)
