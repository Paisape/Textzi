"""Dashboard-side SMS compose & history for a logged-in user's own entity, authenticated via
the user's JWT session -- distinct from /v1/sms/send in main.py, which is the external
programmatic API authenticated by X-Api-Key for integrations built on top of Textzi. There is
no real queue consumer wired up yet, so compose dispatches inline right after accepting."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .config import settings
from .database import get_db
from .dispatch import dispatch_message
from .models import Message, OptOutEntry, Status, Template, User
from .schemas import MessageOut, OptOutEntryCreate, OptOutEntryOut, SmsSendRequest, SmsSendResponse, TemplateSummary
from .security import decrypt_recipient_lenient, encrypt_secret
from .services import DomainError, RateLimitError, assert_not_opted_out, available_balance, debit_wallet, enforce_rate_limit, is_encryption_enabled, mask_mobile, render_template, require_channel_active, resolve_routes, resolve_template, resolve_user_entity, sms_segment_credits

router = APIRouter(prefix="/v1/sms", tags=["sms"])


@router.get("/templates", response_model=list[TemplateSummary])
def list_my_templates(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    templates = db.scalars(select(Template).where(Template.entity_id == entity.id, Template.status == Status.active)).all()
    return [TemplateSummary(id=t.id, alias=t.alias, dlt_template_id=t.dlt_template_id, body=t.body, category=t.category) for t in templates]


@router.post("/compose", response_model=SmsSendResponse)
def compose_sms(payload: SmsSendRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
        # Shared rate-limit key namespace with the external /v1/sms/send API (main.py) -- keyed
        # by entity, the actual tenant/billing boundary, so a customer can't dodge the limit by
        # switching between their own API integration and the dashboard's Compose tab.
        enforce_rate_limit(f"ratelimit:sms:{entity.id}", settings.sms_rate_limit_max_requests, settings.sms_rate_limit_window_seconds)
        require_channel_active(db, entity.id, "sms")
        assert_not_opted_out(db, entity.id, payload.mobile)
        template = resolve_template(db, entity.id, payload.template)
        route_plan = resolve_routes(db, user.id, None)
        rendered_body = render_template(template.body, payload.variables)
        encrypted = is_encryption_enabled(db, entity.id, "sms")
        credits = sms_segment_credits(rendered_body)
        message = Message(
            entity_id=entity.id,
            template_id=template.id,
            recipient=encrypt_secret(payload.mobile) if encrypted else payload.mobile,
            rendered_body=encrypt_secret(rendered_body) if encrypted else rendered_body,
            is_encrypted=encrypted,
            route=route_plan[0],
            route_plan=route_plan,
            credits_charged=credits,
            # Same telemetry the external /v1/sms/send API captures (main.py) -- without this,
            # the admin SMS Log & Report "View" drill-down was silently empty for every message
            # sent through the dashboard's own Compose tab, which is a real send path, not a
            # lesser one.
            request_payload={
                "mobile": mask_mobile(payload.mobile) if encrypted else payload.mobile,
                "template": payload.template,
                "variables": None if encrypted else payload.variables,
                "composed_by_user_id": user.id,
            },
        )
        db.add(message); db.flush()
        debit_wallet(db, entity.id, credits, reference=message.id)  # 1 credit per 160-char segment (services.sms_segment_credits)
        db.commit(); db.refresh(message)
    except RateLimitError as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DomainError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    dispatch_message(db, message)
    db.refresh(message)
    response = SmsSendResponse(status=message.status, message_id=message.id, route=message.route or route_plan[0], balance=available_balance(db, entity.id), credits_charged=credits)
    message.response_payload = response.model_dump()
    db.commit()
    return response


MESSAGE_PAGE_LIMIT_DEFAULT = 50
MESSAGE_PAGE_LIMIT_MAX = 200


@router.get("/messages", response_model=list[MessageOut])
def list_my_messages(limit: int = MESSAGE_PAGE_LIMIT_DEFAULT, offset: int = 0, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Masking is keyed off each message's own `is_encrypted` flag (set at send time), not the
    entity's current live setting -- so toggling encryption off later doesn't retroactively
    reveal older numbers, and toggling it on doesn't retroactively mask older ones."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    limit = max(1, min(limit, MESSAGE_PAGE_LIMIT_MAX))
    offset = max(0, offset)
    messages = db.scalars(select(Message).where(Message.entity_id == entity.id).order_by(Message.created_at.desc()).limit(limit).offset(offset)).all()
    return [
        MessageOut(
            id=m.id,
            recipient=mask_mobile(decrypt_recipient_lenient(m.recipient)) if m.is_encrypted else m.recipient,
            rendered_body="[Encrypted]" if m.is_encrypted else m.rendered_body,
            status=m.status,
            route=m.route,
            credits_charged=m.credits_charged,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]


@router.get("/opt-outs", response_model=list[OptOutEntryOut])
def list_my_opt_outs(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """This entity's own self-service suppression list -- checked before billing/dispatching
    every send (assert_not_opted_out). Not a claim of TRAI NCPR/DND registry integration; see
    OptOutEntry's own docstring in models.py for why."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = db.scalars(select(OptOutEntry).where(OptOutEntry.entity_id == entity.id).order_by(OptOutEntry.created_at.desc())).all()
    return [OptOutEntryOut(id=r.id, mobile=r.mobile, reason=r.reason, created_at=r.created_at.isoformat()) for r in rows]


@router.post("/opt-outs", response_model=OptOutEntryOut)
def add_my_opt_out(payload: OptOutEntryCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = OptOutEntry(entity_id=entity.id, mobile=payload.mobile, reason=payload.reason)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"{payload.mobile} is already on the opt-out list")
    db.refresh(row)
    return OptOutEntryOut(id=row.id, mobile=row.mobile, reason=row.reason, created_at=row.created_at.isoformat())


@router.delete("/opt-outs/{entry_id}")
def remove_my_opt_out(entry_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = db.scalar(select(OptOutEntry).where(OptOutEntry.id == entry_id, OptOutEntry.entity_id == entity.id))
    if not row:
        raise HTTPException(status_code=404, detail="Opt-out entry not found")
    db.delete(row)
    db.commit()
    return {"id": entry_id, "removed": True}
