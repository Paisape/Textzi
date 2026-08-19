"""Bulk template sends to a Segment -- always a template (Meta only allows business-initiated
sends outside the 24h window via an approved template, same constraint waba_inbox.py's own
template-message endpoint already works within). Deliberately its own module, same isolation
principle as every other WABA module: never imports from/into dispatch.py/providers.py/
webhooks.py (SMS)."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import SessionLocal, get_db
from .models import Campaign, CampaignRecipient, Contact, Segment, User, WabaConnection
from .permissions import require_channel_scope
from .schemas import CampaignCreateRequest, CampaignOut, CampaignScheduleRequest
from .security import decrypt_secret
from .services import DomainError, resolve_user_entity
from .waba_dispatch import send_whatsapp_template
from .waba_inbox import segment_matching_contacts
from .waba_meta import MetaApiError, list_message_templates

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/waba/campaigns", tags=["waba-campaigns"], dependencies=[Depends(require_channel_scope("waba"))])


def _campaign_out(campaign: Campaign) -> CampaignOut:
    return CampaignOut(
        id=campaign.id, name=campaign.name, template_name=campaign.template_name, template_language=campaign.template_language,
        body_params=campaign.body_params, segment_id=campaign.segment_id, status=campaign.status,
        total_recipients=campaign.total_recipients, sent_count=campaign.sent_count, failed_count=campaign.failed_count,
        created_at=campaign.created_at.isoformat(), completed_at=campaign.completed_at.isoformat() if campaign.completed_at else None,
        scheduled_at=campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
    )


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _render_preview(body_text: str, params: list[str]) -> str:
    rendered = body_text
    for i, param in enumerate(params, start=1):
        rendered = rendered.replace(f"{{{{{i}}}}}", param)
    return rendered


@router.get("", response_model=list[CampaignOut])
def list_campaigns(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    campaigns = db.scalars(select(Campaign).where(Campaign.entity_id == entity.id).order_by(Campaign.created_at.desc())).all()
    return [_campaign_out(c) for c in campaigns]


@router.post("", response_model=CampaignOut)
def create_campaign(payload: CampaignCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    segment = db.get(Segment, payload.segment_id)
    if not segment or segment.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Segment not found")
    campaign = Campaign(
        entity_id=entity.id, name=payload.name.strip(), template_name=payload.template_name, template_language=payload.template_language,
        body_params=payload.body_params, segment_id=segment.id, created_by_user_id=user.id,
        total_recipients=len(segment_matching_contacts(db, entity.id, segment)),
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return _campaign_out(campaign)


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "sending":
        raise HTTPException(status_code=409, detail="Cannot delete a campaign that's currently sending")
    db.delete(campaign)
    db.commit()
    return {"deleted": True}


def _run_campaign_send(db: Session, entity_id: str, campaign: Campaign, sent_by_user_id: str | None) -> None:
    """The actual send loop -- called from both the manual POST .../send endpoint and
    run_due_campaigns (main.py's scheduler). Sends synchronously, recipient by recipient --
    acceptable for the realistic per-entity contact-list sizes this targets; a genuinely
    large-scale broadcast product would queue this, flagged as a real scaling limit worth
    revisiting if campaign sizes grow into the thousands."""
    connection = db.get(WabaConnection, entity_id)
    if not connection or connection.status != "connected":
        campaign.status = "failed"
        db.commit()
        return

    try:
        templates = list_message_templates(connection.waba_id, decrypt_secret(connection.access_token_encrypted))
    except Exception:
        # Broad on purpose: decrypt_secret can raise cryptography's InvalidToken on a corrupted
        # token, not just MetaApiError from the Meta call -- without catching everything here, an
        # unexpected exception would propagate past this function with the campaign still at
        # status="scheduled", so run_due_campaigns' 5-minute poll would just retry it forever
        # instead of ever marking it failed.
        logger.exception("waba campaigns: could not load templates for campaign_id=%s", campaign.id)
        campaign.status = "failed"
        db.commit()
        return
    template = next((t for t in templates if t["name"] == campaign.template_name and t.get("language") == campaign.template_language), None)
    if not template or template.get("status") != "APPROVED":
        campaign.status = "failed"
        db.commit()
        return
    body_component = next((c for c in template.get("components", []) if c.get("type") == "BODY"), None)
    preview_body = _render_preview(body_component.get("text", ""), campaign.body_params) if body_component else campaign.template_name

    segment = db.get(Segment, campaign.segment_id)
    contacts = segment_matching_contacts(db, entity_id, segment) if segment else []
    campaign.status = "sending"
    campaign.total_recipients = len(contacts)
    db.commit()

    for contact in contacts:
        recipient = CampaignRecipient(campaign_id=campaign.id, contact_id=contact.id)
        db.add(recipient)
        if contact.opted_out or not contact.wa_id:
            recipient.status = "skipped_opted_out"
            db.commit()
            continue
        try:
            send_whatsapp_template(db, entity_id, contact.wa_id, campaign.template_name, campaign.template_language, campaign.body_params, preview_body, sent_by_user_id=sent_by_user_id)
            recipient.status = "sent"
            recipient.sent_at = datetime.now(timezone.utc)
            campaign.sent_count += 1
        except (DomainError, MetaApiError) as exc:
            recipient.status = "failed"
            recipient.error = str(exc)[:300]
            campaign.failed_count += 1
        db.commit()

    campaign.status = "completed"
    campaign.completed_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/{campaign_id}/send", response_model=CampaignOut)
def send_campaign(campaign_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "draft":
        raise HTTPException(status_code=409, detail=f"This campaign has already been {campaign.status}")
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number before sending campaigns")
    _run_campaign_send(db, entity.id, campaign, user.id)
    db.refresh(campaign)
    return _campaign_out(campaign)


@router.post("/{campaign_id}/schedule", response_model=CampaignOut)
def schedule_campaign(campaign_id: str, payload: CampaignScheduleRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "draft":
        raise HTTPException(status_code=409, detail=f"This campaign has already been {campaign.status}")
    try:
        scheduled_at = datetime.fromisoformat(payload.scheduled_at)
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone offset")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="scheduled_at must be in the future")
    campaign.scheduled_at = scheduled_at
    campaign.status = "scheduled"
    db.commit()
    db.refresh(campaign)
    return _campaign_out(campaign)


@router.post("/{campaign_id}/unschedule", response_model=CampaignOut)
def unschedule_campaign(campaign_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != "scheduled":
        raise HTTPException(status_code=409, detail="This campaign isn't scheduled")
    campaign.scheduled_at = None
    campaign.status = "draft"
    db.commit()
    db.refresh(campaign)
    return _campaign_out(campaign)


def run_due_campaigns() -> None:
    """Scheduled job (main.py's lifespan, same IntervalTrigger pattern as CRM sequences/email
    poll) -- picks up any campaign whose scheduled_at has passed and runs it through the exact
    same send logic the manual endpoint uses, so there's only one send path to keep correct."""
    db = SessionLocal()
    try:
        due = db.scalars(
            select(Campaign).where(Campaign.status == "scheduled", Campaign.scheduled_at <= datetime.now(timezone.utc)),
        ).all()
        for campaign in due:
            try:
                _run_campaign_send(db, campaign.entity_id, campaign, campaign.created_by_user_id)
            except Exception:
                logger.exception("waba campaigns: scheduled send failed for campaign_id=%s", campaign.id)
    finally:
        db.close()
