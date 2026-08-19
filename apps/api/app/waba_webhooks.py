"""Inbound events from Meta for WhatsApp Cloud API -- one app-level callback URL shared across
every customer's connected number (see services.waba_webhook_url), never a per-customer URL like
TTBS's DR callback. Deliberately its own module/router, never importing from or importing into
dispatch.py/providers.py/webhooks.py (the SMS-specific pipeline) -- same isolation principle as
every other WABA module in this codebase."""
import hashlib
import hmac
import json
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import waba_media
from .database import get_db
from .models import BusinessHours, Contact, Conversation, ConversationMessage, CsatResponse, SlaPolicy, WabaConnection, WabaWebhookLog, WabaWebhookSubscription
from .security import decrypt_secret, sign_webhook_payload
from .services import client_ip, get_platform_waba_settings, get_platform_waba_webhook_verify_token
from .waba_automation import apply_rules
from .waba_meta import MetaApiError, download_media_bytes, fetch_media_url
from .waba_realtime import message_payload, publish_event

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


def _log_webhook(db: Session, direction: str, status: str, detail: str, phone_number_id: str | None = None, entity_id: str | None = None, ip_address: str | None = None) -> None:
    """Best-effort -- a logging failure must never break webhook processing itself, so this
    swallows its own exceptions rather than letting a DB hiccup turn into a 500 back to Meta."""
    try:
        db.add(WabaWebhookLog(direction=direction, status=status, detail=detail[:300], phone_number_id=phone_number_id, entity_id=entity_id, ip_address=ip_address))
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("waba webhook: failed to write WabaWebhookLog row", exc_info=True)


@router.get("/waba")
def verify_waba_webhook(
    request: Request,
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    """Meta's one-time GET handshake when the webhook URL is (re)saved in the App Dashboard --
    must echo hub.challenge back as plain text on a match, per Meta's own docs."""
    expected = get_platform_waba_webhook_verify_token(db)
    if hub_mode != "subscribe" or not expected or not hmac.compare_digest(hub_verify_token, expected):
        _log_webhook(db, "verify", "rejected", "hub.mode/hub.verify_token mismatch" if expected else "no verify token configured on this platform", ip_address=client_ip(request))
        raise HTTPException(status_code=403, detail="Verification token mismatch")
    _log_webhook(db, "verify", "ok", "handshake succeeded", ip_address=client_ip(request))
    return PlainTextResponse(hub_challenge)


@router.post("/waba")
async def receive_waba_webhook(request: Request, db: Session = Depends(get_db), x_hub_signature_256: str | None = Header(default=None)):
    """Verifies Meta's own HMAC-SHA256 signature (computed over the raw body with Textzi's App
    Secret) before touching the payload at all, then processes inbound messages and delivery
    status updates. Always acks with 200 for anything past signature verification -- a malformed
    or unrecognized entry is logged and skipped rather than raised, since a non-2xx response
    makes Meta retry (and, if it keeps happening, can get the webhook disabled entirely)."""
    raw_body = await request.body()
    ip = client_ip(request)
    _, _, app_secret = get_platform_waba_settings(db)
    if not app_secret:
        _log_webhook(db, "event", "rejected", "WhatsApp not configured on this platform (no App Secret saved)", ip_address=ip)
        raise HTTPException(status_code=403, detail="WhatsApp is not configured on this platform")
    if not x_hub_signature_256 or not x_hub_signature_256.startswith("sha256="):
        _log_webhook(db, "event", "rejected", "missing X-Hub-Signature-256 header", ip_address=ip)
        raise HTTPException(status_code=403, detail="Missing signature")
    expected_signature = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(x_hub_signature_256.removeprefix("sha256="), expected_signature):
        _log_webhook(db, "event", "rejected", "signature did not match (wrong App Secret, or payload tampered)", ip_address=ip)
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        _log_webhook(db, "event", "error", "invalid JSON body", ip_address=ip)
        return {"status": "ignored", "reason": "invalid_json"}

    new_messages: list[tuple[str, ConversationMessage]] = []
    status_updates: list[tuple[str, ConversationMessage]] = []
    last_phone_number_id: str | None = None
    last_entity_id: str | None = None
    unmatched_phone_number_id: str | None = None
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            if not phone_number_id:
                continue
            last_phone_number_id = phone_number_id
            connection = db.scalar(select(WabaConnection).where(WabaConnection.phone_number_id == phone_number_id, WabaConnection.status == "connected"))
            if not connection:
                logger.warning("waba webhook: no connected WabaConnection for phone_number_id=%s", phone_number_id)
                unmatched_phone_number_id = phone_number_id
                continue
            last_entity_id = connection.entity_id
            field = change.get("field")
            if field == "message_template_status_update":
                logger.info("waba webhook: template status update for entity_id=%s: %s", connection.entity_id, value)
                continue
            new_messages += _handle_inbound_messages(db, connection, value)
            status_updates += _handle_statuses(db, connection.entity_id, value)
            _log_errors(connection.entity_id, value)
    db.commit()

    if unmatched_phone_number_id and not last_entity_id:
        _log_webhook(db, "event", "error", f"no connected WabaConnection for phone_number_id={unmatched_phone_number_id}", phone_number_id=unmatched_phone_number_id, ip_address=ip)
    else:
        _log_webhook(
            db, "event", "ok", f"processed {len(new_messages)} message(s), {len(status_updates)} status update(s)",
            phone_number_id=last_phone_number_id, entity_id=last_entity_id, ip_address=ip,
        )

    for entity_id, message in new_messages:
        db.refresh(message)
        publish_event(entity_id, {"type": "message", "message": message_payload(message)})
        _fire_outbound_webhook(db, entity_id, "message.received", message_payload(message))
    for entity_id, message in status_updates:
        publish_event(entity_id, {"type": "message_status", "conversation_id": message.conversation_id, "message_id": message.id, "status": message.status})
        _fire_outbound_webhook(db, entity_id, "message.status", {"conversation_id": message.conversation_id, "message_id": message.id, "status": message.status})
    return {"status": "processed"}


def _fire_outbound_webhook(db: Session, entity_id: str, event: str, data: dict) -> None:
    """Best-effort, synchronous, short-timeout POST to the customer's own configured URL --
    signed the same way Meta signs its webhooks to Textzi (see sign_webhook_payload), so their
    endpoint can verify it actually came from Textzi. A slow or dead customer endpoint must never
    block webhook processing for everyone else, hence the short timeout and blanket exception
    swallow -- no retry queue for now, just a logged miss."""
    subscription = db.get(WabaWebhookSubscription, entity_id)
    if not subscription or not subscription.enabled or not subscription.url:
        return
    body = json.dumps({"event": event, "data": data}).encode()
    signature = sign_webhook_payload(subscription.secret, body)
    try:
        requests.post(subscription.url, data=body, headers={"Content-Type": "application/json", "X-Textzi-Signature": f"sha256={signature}"}, timeout=5)
    except requests.RequestException:
        logger.warning("waba webhook: outbound webhook delivery failed for entity_id=%s url=%s", entity_id, subscription.url, exc_info=True)


def _resolve_contact(db: Session, entity_id: str, wa_id: str, name: str | None) -> tuple[Contact, bool]:
    contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.wa_id == wa_id))
    if not contact:
        contact = Contact(entity_id=entity_id, wa_id=wa_id, name=name)
        db.add(contact)
        db.flush()
        return contact, True
    return contact, False


def _resolve_conversation(db: Session, entity_id: str, contact_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact_id, Conversation.channel == "whatsapp"),
    )
    if not conversation:
        conversation = Conversation(entity_id=entity_id, contact_id=contact_id, channel="whatsapp")
        db.add(conversation)
        db.flush()
    return conversation


_MEDIA_TYPES = {"image", "video", "audio", "document", "sticker"}


def _download_inbound_media(connection: WabaConnection, msg: dict, message_type: str) -> str | None:
    """Best-effort: a failed media download must not lose the inbound message itself -- the row
    is still saved (with media_url left null), just without a locally-hosted copy this time."""
    media_id = msg.get(message_type, {}).get("id")
    if not media_id:
        return None
    try:
        access_token = decrypt_secret(connection.access_token_encrypted)
        url, mime_type = fetch_media_url(media_id, access_token)
        content = download_media_bytes(url, access_token)
        return waba_media.save_media(connection.entity_id, content, mime_type, message_type)
    except MetaApiError:
        logger.warning("waba webhook: could not download inbound media for entity_id=%s", connection.entity_id, exc_info=True)
        return None


def _parse_inbound_content(msg: dict, message_type: str) -> tuple[str | None, dict | None]:
    """Returns (body, payload) for one inbound message. body is the plain-text summary shown in
    the conversation list preview / thread bubble; payload is the structured data for types that
    need it (location/contacts/interactive replies/reactions) -- see ConversationMessage.payload's
    own docstring for the shape per type."""
    if message_type == "text":
        return msg.get("text", {}).get("body"), None
    if message_type in _MEDIA_TYPES:
        return msg.get(message_type, {}).get("caption"), None
    if message_type == "location":
        location = msg.get("location", {})
        return location.get("name") or location.get("address") or "Location shared", location
    if message_type == "contacts":
        contacts = msg.get("contacts", [])
        names = ", ".join(c.get("name", {}).get("formatted_name", "Contact") for c in contacts)
        return names or "Contact shared", {"contacts": contacts}
    if message_type == "interactive":
        interactive = msg.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply")
        if reply:
            return reply.get("title"), {"reply_type": "button_reply" if "button_reply" in interactive else "list_reply", **reply}
        return None, interactive
    if message_type == "reaction":
        reaction = msg.get("reaction", {})
        emoji = reaction.get("emoji", "")
        return f"Reacted {emoji}" if emoji else "Removed reaction", reaction
    if message_type == "button":
        # Legacy quick-reply button tap (older template button format, distinct from the
        # "interactive" button_reply above) -- Meta still sends this shape for some template
        # button taps.
        return msg.get("button", {}).get("text"), msg.get("button")
    if message_type == "order":
        # Sent when a customer taps through a catalog/product message and places an order --
        # catalog_id/product_items(retailer_id, quantity, item_price, currency)/text, per Meta's
        # own order-message schema. Previously fell through to (None, None) here, silently
        # discarding the order contents entirely (the row was still created, just empty).
        order = msg.get("order", {})
        item_count = len(order.get("product_items", []))
        return order.get("text") or f"Order: {item_count} item{'s' if item_count != 1 else ''}", order
    return None, None


def _stamp_sla_due_at(db: Session, entity_id: str, conversation: Conversation, now: datetime) -> None:
    """Starts (or restarts) the first-response clock -- only when there's no pending clock
    already running, so a burst of several inbound messages before any reply doesn't keep pushing
    the deadline out."""
    if conversation.first_response_due_at is not None:
        return
    policy = db.get(SlaPolicy, entity_id)
    if not policy or not policy.enabled:
        return
    conversation.first_response_due_at = now + timedelta(minutes=policy.first_response_minutes)
    conversation.sla_breached = False


def _is_outside_business_hours(db: Session, entity_id: str, now: datetime) -> bool:
    """Same day/time check _maybe_send_business_hours_reply itself uses to decide whether to send
    its own fixed auto-reply -- factored out so waba_automation's "outside_hours" trigger can
    fire without duplicating this logic. Returns False (not outside hours) whenever hours aren't
    configured at all, matching the existing auto-reply's own "nothing to do" default."""
    hours = db.get(BusinessHours, entity_id)
    if not hours or not hours.enabled:
        return False
    try:
        local_now = now.astimezone(ZoneInfo(hours.timezone))
    except Exception:
        return False
    day_key = local_now.strftime("%a").lower()[:3]
    day_hours = hours.schedule.get(day_key)
    if not day_hours:
        return True
    try:
        open_t = time.fromisoformat(day_hours["open"])
        close_t = time.fromisoformat(day_hours["close"])
        return not (open_t <= local_now.time() <= close_t)
    except (KeyError, ValueError):
        return False


def _maybe_send_business_hours_reply(db: Session, connection: WabaConnection, contact: Contact, conversation: Conversation, now: datetime) -> None:
    """Best-effort outside-hours auto-reply -- at most once every 12 hours per conversation, so a
    fast back-and-forth outside hours doesn't repeat the same message on every inbound. A failure
    here (Meta rejects the send, no free-form window, etc.) must never break inbound processing,
    so every error is swallowed."""
    hours = db.get(BusinessHours, connection.entity_id)
    if not hours or not hours.enabled or not hours.outside_hours_message or not contact.wa_id:
        return
    try:
        local_now = now.astimezone(ZoneInfo(hours.timezone))
    except Exception:
        return
    day_key = local_now.strftime("%a").lower()[:3]
    day_hours = hours.schedule.get(day_key)
    if day_hours:
        try:
            open_t = time.fromisoformat(day_hours["open"])
            close_t = time.fromisoformat(day_hours["close"])
            if open_t <= local_now.time() <= close_t:
                return  # inside business hours -- no auto-reply needed
        except (KeyError, ValueError):
            pass
    recent_reply = db.scalar(
        select(ConversationMessage.id).where(
            ConversationMessage.conversation_id == conversation.id, ConversationMessage.direction == "outbound",
            ConversationMessage.created_at >= now - timedelta(hours=12),
        ).limit(1),
    )
    if recent_reply:
        return
    from .waba_dispatch import send_whatsapp_text  # local import, same rationale as waba_automation.py's own reply action
    try:
        send_whatsapp_text(db, connection.entity_id, contact.wa_id, hours.outside_hours_message, sent_by_user_id=None)
    except Exception:
        logger.warning("waba webhook: could not send outside-hours auto-reply for entity_id=%s", connection.entity_id, exc_info=True)


def _handle_inbound_messages(db: Session, connection: WabaConnection, value: dict) -> list[tuple[str, ConversationMessage]]:
    messages = value.get("messages")
    if not messages:
        return []
    profiles = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
    created: list[tuple[str, ConversationMessage]] = []
    for msg in messages:
        wamid = msg.get("id")
        wa_id = msg.get("from")
        if not wamid or not wa_id:
            continue
        # Meta retries webhook delivery on anything short of a fast 2xx -- without this check a
        # retried event would create a duplicate inbound message every time.
        if db.scalar(select(ConversationMessage.id).where(ConversationMessage.meta_message_id == wamid)):
            continue
        contact, is_new_contact = _resolve_contact(db, connection.entity_id, wa_id, profiles.get(wa_id))
        conversation = _resolve_conversation(db, connection.entity_id, contact.id)
        message_type = msg.get("type", "text")
        body, payload = _parse_inbound_content(msg, message_type)
        media_url = _download_inbound_media(connection, msg, message_type) if message_type in _MEDIA_TYPES else None
        timestamp = msg.get("timestamp")
        created_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
        message = ConversationMessage(
            conversation_id=conversation.id, direction="inbound", message_type=message_type,
            body=body, media_url=media_url, payload=payload, meta_message_id=wamid, created_at=created_at,
        )
        db.add(message)
        _stamp_ad_referral(contact, msg.get("referral"))
        conversation.status = "open"
        conversation.last_message_at = created_at
        _stamp_sla_due_at(db, connection.entity_id, conversation, created_at)
        _match_csat_response(db, conversation, message_type, payload)
        db.flush()
        _maybe_send_business_hours_reply(db, connection, contact, conversation, created_at)
        apply_rules(db, connection.entity_id, contact, conversation, body, is_new_contact, _is_outside_business_hours(db, connection.entity_id, created_at))
        created.append((connection.entity_id, message))
    return created


def _stamp_ad_referral(contact: Contact, referral: dict | None) -> None:
    """Meta attaches a `referral` object to the first inbound message of a conversation that
    started from a Click-to-WhatsApp ad (source_id/source_type/source_url/headline/body/
    media_type/ctwa_clid) -- captured once, on first touch only, so a contact's own attribution
    survives even after the conversation moves on to unrelated messages with no referral block.
    Stored on Contact.custom_attributes (the existing flexible per-contact field) rather than a
    new column, matching this codebase's own stated reasoning for that column's design."""
    if not referral or contact.custom_attributes.get("ad_referral"):
        return
    contact.custom_attributes = {**contact.custom_attributes, "ad_referral": referral}


def _match_csat_response(db: Session, conversation: Conversation, message_type: str, payload: dict | None) -> None:
    """A CSAT rating request is sent as a quick-reply template with buttons "1".."5" (see
    waba_inbox.update_conversation) -- a matching inbound button_reply here is the customer's
    answer, not a normal message, so it fills in the newest unanswered CsatResponse row rather
    than needing its own message type."""
    if message_type != "interactive" or not payload:
        return
    title = payload.get("title", "")
    if title not in {"1", "2", "3", "4", "5"}:
        return
    pending = db.scalar(
        select(CsatResponse).where(CsatResponse.conversation_id == conversation.id, CsatResponse.rating.is_(None))
        .order_by(CsatResponse.requested_at.desc()).limit(1),
    )
    if pending:
        pending.rating = int(title)
        pending.responded_at = datetime.now(timezone.utc)


def _handle_statuses(db: Session, entity_id: str, value: dict) -> list[tuple[str, ConversationMessage]]:
    updated: list[tuple[str, ConversationMessage]] = []
    for status_update in value.get("statuses", []):
        wamid = status_update.get("id")
        status = status_update.get("status")
        if not wamid or status not in {"sent", "delivered", "read", "failed"}:
            continue
        message = db.scalar(select(ConversationMessage).where(ConversationMessage.meta_message_id == wamid))
        if message:
            message.status = status
            if status == "failed":
                errors = status_update.get("errors", [])
                if errors:
                    message.error = "; ".join(e.get("title", "Unknown error") for e in errors)[:300]
            updated.append((entity_id, message))
    return updated


def _log_errors(entity_id: str, value: dict) -> None:
    """Async delivery errors Meta reports outside the statuses array (entry.changes.value.errors)
    -- e.g. a webhook payload Meta couldn't fully process. No message to attach these to, so
    logged for now rather than silently dropped; not surfaced in-app since there's nothing
    actionable an agent could do with a raw Graph API error code."""
    for error in value.get("errors", []):
        logger.warning("waba webhook: async error for entity_id=%s: %s", entity_id, error)
