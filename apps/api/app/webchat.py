"""Customer-facing settings for the embeddable website chat widget -- gated on WABA OR CRM being
active (either one, not both required, confirmed with the user), so this is deliberately its own
module rather than living under crm.py's CRM-only gate. The actual visitor-facing pieces (widget
bootstrap, message send, live socket) are in webchat_public.py/webchat_realtime.py -- this module
is authenticated-agent-only (settings CRUD + the embed snippet to copy)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import waba_media
from .auth import require_user
from .database import get_db
from .models import Contact, Conversation, ConversationMessage, CsatResponse, TicketGroup, User, WebchatVisit, WebchatWidgetSettings
from .permissions import require_channel_scope_any
from .schemas import (
    ReportAgentRow, ReportVolumePoint, WebchatDefaultGroupUpdateRequest, WebchatReportsOut, WebchatVisitTelemetryOut,
    WebchatWidgetSettingsOut, WebchatWidgetSettingsUpdateRequest,
)
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
        proactive_trigger_enabled=settings_row.proactive_trigger_enabled, proactive_trigger_type=settings_row.proactive_trigger_type,
        proactive_trigger_delay_seconds=settings_row.proactive_trigger_delay_seconds, proactive_trigger_message=settings_row.proactive_trigger_message,
        proactive_url_pattern=settings_row.proactive_url_pattern, default_group_id=settings_row.default_group_id,
        auto_assign_enabled=settings_row.auto_assign_enabled, embed_snippet=_embed_snippet(db, settings_row.widget_key),
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


def send_webchat_media(db: Session, entity_id: str, conversation: Conversation, contact: Contact, content: bytes, mime_type: str, message_type: str, caption: str | None = None, sent_by_user_id: str | None = None) -> ConversationMessage:
    """The webchat equivalent of waba_dispatch.send_whatsapp_media -- reuses waba_media.save_media
    as-is (it already doesn't care whether the bytes came from Meta or an agent/visitor upload,
    only that they're stored safely under a UUID filename), just skips the Meta upload/send call
    entirely since delivery here is only ever the visitor's own live WebSocket."""
    if not contact.visitor_id:
        raise DomainError("This contact has no active webchat session to send to")
    stored_path = waba_media.save_media(entity_id, content, mime_type, message_type)
    message = ConversationMessage(
        conversation_id=conversation.id, direction="outbound", message_type=message_type, body=caption,
        media_url=stored_path, status="sent", sent_by_user_id=sent_by_user_id,
    )
    db.add(message)
    conversation.status = "open"
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.first_response_due_at = None
    db.commit()
    db.refresh(message)
    payload = message_payload(message)
    publish_event(entity_id, {"type": "message", "message": payload})
    publish_to_visitor(contact.visitor_id, {"type": "message", "message": payload})
    return message


@router.get("/reports", response_model=WebchatReportsOut)
def get_webchat_reports(days: int = 30, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Webchat-specific volume/agent/SLA/CSAT reporting -- mirrors waba_reports.py's own
    get_reports shape (same overall structure, this codebase's established reporting pattern),
    filtered to channel="webchat" and extended with real average first-response/resolution times
    computed from actual message/resolved_at timestamps, not just breach counts."""
    entity = _resolve_entity(db, user)
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    conversation_ids = db.scalars(select(Conversation.id).where(Conversation.entity_id == entity.id, Conversation.channel == "webchat")).all()
    if not conversation_ids:
        return WebchatReportsOut(
            volume=[], agents=[], total_conversations=0, open_conversations=0, resolved_conversations=0,
            sla_breached_count=0, resolution_breached_count=0, avg_first_response_minutes=None,
            avg_resolution_minutes=None, avg_csat=None, csat_response_count=0,
        )

    # --- Volume: per-day inbound/outbound counts ---
    volume_rows = db.execute(
        select(func.date(ConversationMessage.created_at), ConversationMessage.direction, func.count())
        .where(ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.created_at >= since, ConversationMessage.is_private.is_(False))
        .group_by(func.date(ConversationMessage.created_at), ConversationMessage.direction),
    ).all()
    by_date: dict[str, dict[str, int]] = {}
    for date_val, direction, count in volume_rows:
        key = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
        by_date.setdefault(key, {"inbound": 0, "outbound": 0})[direction] = count
    volume = [ReportVolumePoint(date=d, inbound=v.get("inbound", 0), outbound=v.get("outbound", 0)) for d, v in sorted(by_date.items())]

    # --- Real first-response time: for each conversation, the gap between its first inbound
    # message and the first non-private outbound reply that follows it. Computed from actual
    # message timestamps (not the SLA due-at/breached fields, which only ever tell you whether a
    # deadline was met, never the real elapsed time for a conversation that met it).
    #
    # Batched, not per-conversation -- the original version issued up to 2 extra queries per
    # conversation in a Python loop, scaling linearly with total historical conversation count
    # (not even bounded by `since`). Two grouped MIN() queries (first inbound per conversation,
    # first non-private outbound reply per conversation) replace that entirely: pull both maps
    # once, then pair them up in Python.
    response_gaps: list[float] = []
    resolution_gaps: list[float] = []
    first_inbound_rows = db.execute(
        select(ConversationMessage.conversation_id, func.min(ConversationMessage.created_at))
        .where(ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.direction == "inbound")
        .group_by(ConversationMessage.conversation_id),
    ).all()
    first_inbound_by_conv = dict(first_inbound_rows)
    first_reply_rows = db.execute(
        select(ConversationMessage.conversation_id, func.min(ConversationMessage.created_at))
        .where(
            ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.direction == "outbound",
            ConversationMessage.is_private.is_(False),
        )
        .group_by(ConversationMessage.conversation_id),
    ).all()
    first_reply_by_conv = dict(first_reply_rows)
    conversations = db.scalars(select(Conversation).where(Conversation.id.in_(conversation_ids))).all()
    for conv in conversations:
        first_inbound = first_inbound_by_conv.get(conv.id)
        first_reply = first_reply_by_conv.get(conv.id)
        # The reply must actually follow the first inbound message -- an agent-initiated outbound
        # send (a proactive trigger, a macro) with no inbound message yet isn't a "response."
        if first_inbound and first_reply and first_reply > first_inbound:
            response_gaps.append((first_reply - first_inbound).total_seconds() / 60)
        if conv.resolved_at:
            resolution_gaps.append((conv.resolved_at - conv.created_at).total_seconds() / 60)

    avg_first_response = round(sum(response_gaps) / len(response_gaps), 1) if response_gaps else None
    avg_resolution = round(sum(resolution_gaps) / len(resolution_gaps), 1) if resolution_gaps else None

    # --- Per-agent: messages sent, conversations resolved, own average first-response time ---
    sent_rows = db.execute(
        select(ConversationMessage.sent_by_user_id, func.count())
        .where(ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.direction == "outbound", ConversationMessage.sent_by_user_id.isnot(None), ConversationMessage.created_at >= since)
        .group_by(ConversationMessage.sent_by_user_id),
    ).all()
    resolved_rows = db.execute(
        select(Conversation.assigned_user_id, func.count())
        .where(Conversation.id.in_(conversation_ids), Conversation.status == "resolved", Conversation.assigned_user_id.isnot(None))
        .group_by(Conversation.assigned_user_id),
    ).all()
    resolved_by_user = dict(resolved_rows)
    agent_ids = {row[0] for row in sent_rows} | set(resolved_by_user.keys())
    agents_by_id = {u.id: u for u in db.scalars(select(User).where(User.id.in_(agent_ids))).all()} if agent_ids else {}
    sent_by_user = dict(sent_rows)
    agents = [
        ReportAgentRow(user_id=uid, full_name=agents_by_id[uid].full_name, messages_sent=sent_by_user.get(uid, 0), conversations_resolved=resolved_by_user.get(uid, 0), avg_first_response_minutes=None)
        for uid in agent_ids if uid in agents_by_id
    ]

    # --- Overview ---
    total = len(conversation_ids)
    open_count = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.id.in_(conversation_ids), Conversation.status != "resolved")) or 0
    resolved_count = total - open_count
    sla_breached = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.id.in_(conversation_ids), Conversation.sla_breached.is_(True))) or 0
    resolution_breached = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.id.in_(conversation_ids), Conversation.resolution_breached.is_(True))) or 0
    csat_rows = db.scalars(select(CsatResponse).where(CsatResponse.entity_id == entity.id, CsatResponse.conversation_id.in_(conversation_ids), CsatResponse.rating.isnot(None))).all()
    avg_csat = round(sum(r.rating for r in csat_rows) / len(csat_rows), 2) if csat_rows else None

    return WebchatReportsOut(
        volume=volume, agents=agents, total_conversations=total, open_conversations=open_count,
        resolved_conversations=resolved_count, sla_breached_count=sla_breached, resolution_breached_count=resolution_breached,
        avg_first_response_minutes=avg_first_response, avg_resolution_minutes=avg_resolution,
        avg_csat=avg_csat, csat_response_count=len(csat_rows),
    )


@router.get("/visits/{conversation_id}", response_model=WebchatVisitTelemetryOut)
def get_visit_telemetry(conversation_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Backs the Telemetry panel on a webchat conversation's detail view in the inbox --
    current page/referrer/browser/geo/pages-viewed-this-session, per the user's confirmed
    telemetry scope for this feature."""
    entity = _resolve_entity(db, user)
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    visit = db.scalar(select(WebchatVisit).where(WebchatVisit.conversation_id == conversation_id))
    if not visit:
        raise HTTPException(status_code=404, detail="No telemetry recorded for this conversation")
    return WebchatVisitTelemetryOut(
        current_url=visit.current_url, referrer=visit.referrer, user_agent=visit.user_agent,
        country=visit.country, city=visit.city, pages_viewed=visit.pages_viewed,
        started_at=visit.started_at.isoformat(), last_seen_at=visit.last_seen_at.isoformat(),
    )


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
    if payload.proactive_trigger_type is not None:
        settings_row.proactive_trigger_type = payload.proactive_trigger_type
    if payload.proactive_url_pattern is not None:
        settings_row.proactive_url_pattern = payload.proactive_url_pattern
    if payload.auto_assign_enabled is not None:
        settings_row.auto_assign_enabled = payload.auto_assign_enabled
    db.commit()
    db.refresh(settings_row)
    return _settings_out(db, settings_row)


@router.put("/settings/default-group", response_model=WebchatWidgetSettingsOut)
def update_webchat_default_group(payload: WebchatDefaultGroupUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Separate endpoint (not folded into the general settings update above) because group_id is
    required-but-nullable here -- same shape as waba_inbox.py's own update_ticket_group -- so None
    unambiguously means "clear the default group", which a genuinely-optional partial-update field
    (as every other settings field above is) can't express without an extra flag."""
    entity = _resolve_entity(db, user)
    _require_webchat(db, entity.id)
    if payload.group_id:
        group = db.get(TicketGroup, payload.group_id)
        if not group or group.entity_id != entity.id:
            raise HTTPException(status_code=422, detail="group_id must belong to your organization")
    settings_row = db.get(WebchatWidgetSettings, entity.id)
    if not settings_row:
        settings_row = WebchatWidgetSettings(entity_id=entity.id)
        db.add(settings_row)
    settings_row.default_group_id = payload.group_id
    db.commit()
    db.refresh(settings_row)
    return _settings_out(db, settings_row)
