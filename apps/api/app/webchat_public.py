"""Unauthenticated endpoints the embeddable widget script calls directly from a visitor's browser
on a third-party website, plus the widget script itself (GET /widget.js -- a plain string
constant, no build step, deliberately framework-free since it has to run inside an arbitrary
third-party page and stay tiny). Same posture as crm_public.py/public.py: no require_user
anywhere in this file. Origin-checked against WebchatWidgetSettings.allowed_origins on every call,
since (confirmed via research this session) a WebSocket handshake isn't covered by the app's
regular CORSMiddleware the way a normal HTTP request is -- for the plain HTTP endpoints here,
standard CORSMiddleware DOES apply, but the Origin check is done manually anyway so the same
allowed_origins list is the single source of truth for both the HTTP and WebSocket paths, not two
separate mechanisms to keep in sync."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .geoip import lookup_geo
from .models import Contact, Conversation, ConversationMessage, CsatResponse, WebchatVisit, WebchatWidgetSettings
from .schemas import WebchatCsatRequest, WebchatMessageRequest, WebchatMessageResponse, WebchatVisitRequest, WebchatVisitResponse
from .services import client_ip, is_outside_business_hours
from .turnstile import require_turnstile
from .waba_realtime import message_payload, publish_event
from .webchat_widget_js import WIDGET_JS

logger = logging.getLogger("textzi.webchat")

router = APIRouter(prefix="/v1/public/webchat", tags=["webchat"])


@router.get("/widget.js")
def get_widget_script():
    return Response(content=WIDGET_JS, media_type="application/javascript")


def _widget_settings(db: Session, widget_key: str) -> WebchatWidgetSettings:
    settings_row = db.scalar(select(WebchatWidgetSettings).where(WebchatWidgetSettings.widget_key == widget_key))
    if not settings_row or not settings_row.enabled:
        raise HTTPException(status_code=404, detail="Widget not found")
    return settings_row


def _check_origin(request: Request, settings_row: WebchatWidgetSettings) -> None:
    # allowed_origins empty means "not configured yet" -- fail closed, not open, so a widget
    # can't be embedded anywhere until the customer explicitly allowlists at least one domain.
    origin = request.headers.get("origin")
    if not settings_row.allowed_origins or origin not in settings_row.allowed_origins:
        raise HTTPException(status_code=403, detail="This domain is not allowed to embed this widget")


@router.post("/{widget_key}/visit", response_model=WebchatVisitResponse)
def record_visit(widget_key: str, payload: WebchatVisitRequest, request: Request, db: Session = Depends(get_db)):
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)

    now = datetime.now(timezone.utc)
    visit = db.scalar(select(WebchatVisit).where(WebchatVisit.entity_id == settings_row.entity_id, WebchatVisit.visitor_id == payload.visitor_id))
    if not visit:
        ip = client_ip(request)
        country, city = lookup_geo(ip) if ip else (None, None)
        visit = WebchatVisit(
            entity_id=settings_row.entity_id, visitor_id=payload.visitor_id, current_url=payload.current_url,
            referrer=payload.referrer, user_agent=request.headers.get("user-agent"), ip_address=ip,
            country=country, city=city, pages_viewed=[{"url": payload.current_url, "viewed_at": now.isoformat()}],
        )
        db.add(visit)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            visit = db.scalar(select(WebchatVisit).where(WebchatVisit.entity_id == settings_row.entity_id, WebchatVisit.visitor_id == payload.visitor_id))
            if not visit:
                raise
    else:
        visit.current_url = payload.current_url
        visit.last_seen_at = now
        pages = list(visit.pages_viewed or [])
        if not pages or pages[-1].get("url") != payload.current_url:
            pages.append({"url": payload.current_url, "viewed_at": now.isoformat()})
        visit.pages_viewed = pages
    db.commit()

    offline = is_outside_business_hours(db, settings_row.entity_id, now)
    return WebchatVisitResponse(
        greeting_message=settings_row.greeting_message, bubble_color=settings_row.bubble_color,
        is_online=not offline, offline_message=settings_row.offline_message,
        proactive_trigger_enabled=settings_row.proactive_trigger_enabled,
        proactive_trigger_delay_seconds=settings_row.proactive_trigger_delay_seconds,
        proactive_trigger_message=settings_row.proactive_trigger_message,
    )


def _find_or_create_webchat_contact(db: Session, entity_id: str, visitor_id: str, name: str | None, email: str | None) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.visitor_id == visitor_id))
    if contact:
        if name and not contact.name:
            contact.name = name
        if email and not contact.email:
            contact.email = email
        return contact
    contact = Contact(entity_id=entity_id, visitor_id=visitor_id, name=name, email=email)
    db.add(contact)
    # Same race as every other find-or-create in this codebase (crm.py's _resolve_or_create_contact,
    # crm_email.py's _find_or_create_contact) -- two rapid messages from the same brand-new visitor
    # (e.g. a double-click on send) can both pass the SELECT above before either commits.
    # uq_contacts_entity_visitor_id is the real guarantee.
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.visitor_id == visitor_id))
        if not contact:
            raise
    return contact


def _find_or_create_webchat_conversation(db: Session, entity_id: str, contact_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact_id, Conversation.channel == "webchat"),
    )
    if conversation:
        return conversation
    conversation = Conversation(entity_id=entity_id, contact_id=contact_id, channel="webchat")
    db.add(conversation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        conversation = db.scalar(
            select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact_id, Conversation.channel == "webchat"),
        )
        if not conversation:
            raise
    return conversation


@router.post("/{widget_key}/message", response_model=WebchatMessageResponse)
def send_visitor_message(widget_key: str, payload: WebchatMessageRequest, request: Request, db: Session = Depends(get_db)):
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)
    require_turnstile(payload.turnstile_token, request, db)

    contact = _find_or_create_webchat_contact(db, settings_row.entity_id, payload.visitor_id, payload.name, payload.email)
    conversation = _find_or_create_webchat_conversation(db, settings_row.entity_id, contact.id)

    now = datetime.now(timezone.utc)
    message = ConversationMessage(conversation_id=conversation.id, direction="inbound", message_type="text", body=payload.body, status="received")
    db.add(message)
    conversation.status = "open"
    conversation.last_message_at = now

    visit = db.scalar(select(WebchatVisit).where(WebchatVisit.entity_id == settings_row.entity_id, WebchatVisit.visitor_id == payload.visitor_id))
    if visit:
        visit.contact_id = contact.id
        visit.conversation_id = conversation.id

    db.commit()
    db.refresh(message)
    publish_event(settings_row.entity_id, {"type": "message", "message": message_payload(message)})
    return WebchatMessageResponse(conversation_id=conversation.id, message_id=message.id)


@router.post("/{widget_key}/csat")
def submit_csat(widget_key: str, payload: WebchatCsatRequest, request: Request, db: Session = Depends(get_db)):
    """The widget's own inline 1-5 rating UI submits here once the visitor answers -- fills in
    the newest unanswered CsatResponse row for this visitor's conversation, same "newest
    unanswered row wins" matching logic waba_webhooks._match_csat_response already uses for the
    WhatsApp side, just reached over HTTP instead of an inbound Meta webhook."""
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)

    contact = db.scalar(select(Contact).where(Contact.entity_id == settings_row.entity_id, Contact.visitor_id == payload.visitor_id))
    if not contact:
        raise HTTPException(status_code=404, detail="Unknown visitor")
    conversation = db.scalar(select(Conversation).where(Conversation.entity_id == settings_row.entity_id, Conversation.contact_id == contact.id, Conversation.channel == "webchat"))
    if not conversation:
        raise HTTPException(status_code=404, detail="No conversation for this visitor")
    response_row = db.scalar(
        select(CsatResponse).where(CsatResponse.conversation_id == conversation.id, CsatResponse.rating.is_(None))
        .order_by(CsatResponse.requested_at.desc()).limit(1),
    )
    if not response_row:
        raise HTTPException(status_code=404, detail="No pending rating request for this conversation")
    response_row.rating = payload.rating
    response_row.responded_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok"}
