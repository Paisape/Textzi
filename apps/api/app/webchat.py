"""Customer-facing settings for the embeddable website chat widget -- gated on WABA OR CRM being
active (either one, not both required, confirmed with the user), so this is deliberately its own
module rather than living under crm.py's CRM-only gate. The actual visitor-facing pieces (widget
bootstrap, message send, live socket) are in webchat_public.py/webchat_realtime.py -- this module
is authenticated-agent-only (settings CRUD + the embed snippet to copy)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import Contact, Conversation, ConversationMessage, User, WebchatWidgetSettings
from .permissions import require_channel_scope_any
from .schemas import WebchatWidgetSettingsOut, WebchatWidgetSettingsUpdateRequest
from .services import DomainError, channel_active, get_platform_company_info, resolve_user_entity
from .waba_realtime import message_payload, publish_event
from .webchat_realtime import publish_to_visitor

router = APIRouter(prefix="/v1/webchat", tags=["webchat"], dependencies=[Depends(require_channel_scope_any(["waba", "crm"]))])


def _require_webchat(db: Session, entity_id: str) -> None:
    if not (channel_active(db, entity_id, "waba") or channel_active(db, entity_id, "crm")):
        raise HTTPException(status_code=422, detail="Activate WhatsApp or CRM to use the website chat widget")


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _embed_snippet(db: Session, widget_key: str) -> str:
    # Points at the UNAUTHENTICATED /v1/public/webchat/widget.js route (webchat_public.py) -- an
    # anonymous visitor's browser has no session to authenticate with, so the script itself can't
    # live under this module's own require_channel_scope_any-gated router.
    base_url = get_platform_company_info(db).public_api_base_url
    if not base_url:
        return ""
    src = f"{base_url.rstrip('/')}/v1/public/webchat/widget.js"
    return f'<script src="{src}" data-widget-key="{widget_key}" async></script>'


def _settings_out(db: Session, settings_row: WebchatWidgetSettings) -> WebchatWidgetSettingsOut:
    return WebchatWidgetSettingsOut(
        enabled=settings_row.enabled, widget_key=settings_row.widget_key, allowed_origins=settings_row.allowed_origins,
        bubble_color=settings_row.bubble_color, greeting_message=settings_row.greeting_message, offline_message=settings_row.offline_message,
        proactive_trigger_enabled=settings_row.proactive_trigger_enabled, proactive_trigger_delay_seconds=settings_row.proactive_trigger_delay_seconds,
        proactive_trigger_message=settings_row.proactive_trigger_message, embed_snippet=_embed_snippet(db, settings_row.widget_key),
    )


def send_webchat_text(db: Session, entity_id: str, conversation: Conversation, contact: Contact, body: str, sent_by_user_id: str | None = None) -> ConversationMessage:
    """The webchat equivalent of waba_dispatch.send_whatsapp_text -- called from
    waba_inbox.py's send_conversation_message (the shared composer, per the "one inbox, three
    channels" design) and from the Macro "reply" action, both of which previously hardcoded
    send_whatsapp_text and silently no-op'd for a webchat contact (contact.wa_id is always None
    for one). No external API to call -- delivery is just publishing onto the visitor's own
    Redis channel; the widget's WebSocket relays it straight to their open tab."""
    if not contact.visitor_id:
        raise DomainError("This contact has no active webchat session to send to")
    message = ConversationMessage(conversation_id=conversation.id, direction="outbound", message_type="text", body=body, status="sent", sent_by_user_id=sent_by_user_id)
    db.add(message)
    conversation.status = "open"
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.first_response_due_at = None
    db.commit()
    db.refresh(message)
    publish_event(entity_id, {"type": "message", "message": message_payload(message)})
    publish_to_visitor(contact.visitor_id, {"type": "message", "message": message_payload(message)})
    return message


@router.get("/settings", response_model=WebchatWidgetSettingsOut)
def get_webchat_settings(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    settings_row = db.get(WebchatWidgetSettings, entity.id)
    if not settings_row:
        settings_row = WebchatWidgetSettings(entity_id=entity.id)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return _settings_out(db, settings_row)


@router.put("/settings", response_model=WebchatWidgetSettingsOut)
def update_webchat_settings(payload: WebchatWidgetSettingsUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_webchat(db, entity.id)
    settings_row = db.get(WebchatWidgetSettings, entity.id)
    if not settings_row:
        settings_row = WebchatWidgetSettings(entity_id=entity.id)
        db.add(settings_row)
    if payload.enabled is not None:
        settings_row.enabled = payload.enabled
    if payload.allowed_origins is not None:
        settings_row.allowed_origins = payload.allowed_origins
    if payload.bubble_color is not None:
        settings_row.bubble_color = payload.bubble_color
    if payload.greeting_message is not None:
        settings_row.greeting_message = payload.greeting_message
    if payload.offline_message is not None:
        settings_row.offline_message = payload.offline_message
    if payload.proactive_trigger_enabled is not None:
        settings_row.proactive_trigger_enabled = payload.proactive_trigger_enabled
    if payload.proactive_trigger_delay_seconds is not None:
        settings_row.proactive_trigger_delay_seconds = payload.proactive_trigger_delay_seconds
    if payload.proactive_trigger_message is not None:
        settings_row.proactive_trigger_message = payload.proactive_trigger_message
    db.commit()
    db.refresh(settings_row)
    return _settings_out(db, settings_row)
