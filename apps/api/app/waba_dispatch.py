"""Outbound WhatsApp send pipeline -- resolves a connected WabaConnection, the target Contact/
Conversation, calls Meta directly (waba_meta.py), and persists the result. Deliberately its own
module, never importing from or importing into dispatch.py/providers.py/webhooks.py (the
SMS-specific pipeline) -- same isolation principle as waba.py itself."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import waba_media
from .models import Contact, Conversation, ConversationMessage, WabaApiCallLog, WabaConnection
from .security import decrypt_secret
from .services import DomainError, channel_active, check_message_quota, increment_message_usage
from .waba_meta import (
    MetaApiError, send_contact_message, send_interactive_button_message, send_interactive_list_message,
    send_location_message, send_media_message, send_product_list_message, send_product_message,
    send_reaction_message, send_read_receipt, send_template_message, send_text_message, upload_media,
)
from .waba_realtime import message_payload, publish_event


def _log_api_call(db: Session, entity_id: str, action: str, status: str, detail: str, to_wa_id: str | None = None) -> None:
    """Best-effort -- a logging failure must never break an otherwise-successful send."""
    try:
        db.add(WabaApiCallLog(entity_id=entity_id, action=action, status=status, detail=detail[:300], to_wa_id=to_wa_id))
        db.commit()
    except Exception:
        db.rollback()


def _resolve_send_target(db: Session, entity_id: str, to_wa_id: str) -> tuple[WabaConnection, Conversation]:
    """Shared setup for every outbound send: confirms the channel is active and the contact
    hasn't opted out, then finds-or-creates the Contact/Conversation this message belongs to.
    Raises DomainError for anything the caller should show back to the user."""
    if not channel_active(db, entity_id, "waba"):
        raise DomainError("Connect a WhatsApp number before sending messages")
    check_message_quota(db, entity_id, "waba")

    connection = db.get(WabaConnection, entity_id)
    if not connection or connection.status != "connected":
        raise DomainError("Connect a WhatsApp number before sending messages")

    contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.wa_id == to_wa_id))
    if not contact:
        contact = Contact(entity_id=entity_id, wa_id=to_wa_id)
        db.add(contact)
        try:
            db.flush()
        except IntegrityError:
            # uq_contacts_entity_wa_id -- a concurrent send to this same brand-new wa_id can
            # insert first. Re-fetch the row the other request just created instead of crashing.
            db.rollback()
            contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.wa_id == to_wa_id))
            if not contact:
                raise
    if contact.opted_out:
        raise DomainError("This contact has opted out of WhatsApp messages")

    conversation = db.scalar(
        select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact.id, Conversation.channel == "whatsapp"),
    )
    if not conversation:
        conversation = Conversation(entity_id=entity_id, contact_id=contact.id, channel="whatsapp")
        db.add(conversation)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            conversation = db.scalar(
                select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact.id, Conversation.channel == "whatsapp"),
            )
            if not conversation:
                raise
    return connection, conversation


def _persist_outbound(db: Session, entity_id: str, conversation: Conversation, message_type: str, body: str | None, media_url: str | None, wamid: str, sent_by_user_id: str | None, payload: dict | None = None) -> ConversationMessage:
    now = datetime.now(timezone.utc)
    message = ConversationMessage(
        conversation_id=conversation.id, direction="outbound", message_type=message_type,
        body=body, media_url=media_url, payload=payload, meta_message_id=wamid, status="sent", sent_by_user_id=sent_by_user_id,
    )
    db.add(message)
    conversation.status = "open"
    conversation.last_message_at = now
    conversation.first_response_due_at = None
    increment_message_usage(db, entity_id, "waba")
    db.commit()
    db.refresh(message)
    publish_event(entity_id, {"type": "message", "message": message_payload(message)})
    return message


def send_whatsapp_text(db: Session, entity_id: str, to_wa_id: str, body: str, sent_by_user_id: str | None = None) -> ConversationMessage:
    """Sends a free-form text message. Only works inside Meta's 24-hour customer-service window;
    outside it, use send_whatsapp_template instead (Meta rejects a free-form send with a
    MetaApiError, which callers already propagate as a clean 422)."""
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        wamid = send_text_message(connection.phone_number_id, access_token, to_wa_id, body)
    except MetaApiError as exc:
        _log_api_call(db, entity_id, "send_text", "error", str(exc), to_wa_id)
        raise
    _log_api_call(db, entity_id, "send_text", "ok", "sent", to_wa_id)
    return _persist_outbound(db, entity_id, conversation, "text", body, None, wamid, sent_by_user_id)


def send_whatsapp_media(db: Session, entity_id: str, to_wa_id: str, content: bytes, filename: str, mime_type: str, media_type: str, caption: str | None, sent_by_user_id: str | None = None) -> ConversationMessage:
    """Uploads the file to Meta, sends it, and separately persists Textzi's own copy under
    waba_media.save_media -- Meta's own media URLs expire, so media_url always points at
    Textzi's own storage/serving endpoint, never at Meta directly."""
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        meta_media_id = upload_media(connection.phone_number_id, access_token, content, filename, mime_type)
        wamid = send_media_message(connection.phone_number_id, access_token, to_wa_id, media_type, meta_media_id, caption)
    except MetaApiError as exc:
        _log_api_call(db, entity_id, "send_media", "error", str(exc), to_wa_id)
        raise
    _log_api_call(db, entity_id, "send_media", "ok", "sent", to_wa_id)
    stored_path = waba_media.save_media(entity_id, content, mime_type, media_type)
    return _persist_outbound(db, entity_id, conversation, media_type, caption, stored_path, wamid, sent_by_user_id)


def send_whatsapp_template(db: Session, entity_id: str, to_wa_id: str, template_name: str, language_code: str, body_params: list[str], preview_body: str, sent_by_user_id: str | None = None) -> ConversationMessage:
    """Template sends work outside the 24-hour window (that's their whole purpose), unlike
    send_whatsapp_text. preview_body is the already-filled-in text Textzi's own UI showed the
    agent before sending -- stored as the message body so the thread reads naturally, since Meta
    itself doesn't echo back the rendered template text in its response."""
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        wamid = send_template_message(connection.phone_number_id, access_token, to_wa_id, template_name, language_code, body_params)
    except MetaApiError as exc:
        _log_api_call(db, entity_id, "send_template", "error", str(exc), to_wa_id)
        raise
    _log_api_call(db, entity_id, "send_template", "ok", f"sent template={template_name}", to_wa_id)
    return _persist_outbound(db, entity_id, conversation, "text", preview_body, None, wamid, sent_by_user_id)


def send_whatsapp_location(db: Session, entity_id: str, to_wa_id: str, latitude: float, longitude: float, name: str | None, address: str | None, sent_by_user_id: str | None = None) -> ConversationMessage:
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    wamid = send_location_message(connection.phone_number_id, access_token, to_wa_id, latitude, longitude, name, address)
    payload = {"latitude": latitude, "longitude": longitude, "name": name, "address": address}
    return _persist_outbound(db, entity_id, conversation, "location", name or address, None, wamid, sent_by_user_id, payload)


def send_whatsapp_contact(db: Session, entity_id: str, to_wa_id: str, contacts: list[dict], sent_by_user_id: str | None = None) -> ConversationMessage:
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    wamid = send_contact_message(connection.phone_number_id, access_token, to_wa_id, contacts)
    names = ", ".join(c.get("name", {}).get("formatted_name", "Contact") for c in contacts)
    return _persist_outbound(db, entity_id, conversation, "contacts", names, None, wamid, sent_by_user_id, {"contacts": contacts})


def send_whatsapp_interactive_buttons(db: Session, entity_id: str, to_wa_id: str, body_text: str, buttons: list[dict], sent_by_user_id: str | None = None) -> ConversationMessage:
    if not 1 <= len(buttons) <= 3:
        raise DomainError("An interactive message needs between 1 and 3 buttons")
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    wamid = send_interactive_button_message(connection.phone_number_id, access_token, to_wa_id, body_text, buttons)
    return _persist_outbound(db, entity_id, conversation, "interactive_button", body_text, None, wamid, sent_by_user_id, {"buttons": buttons})


def send_whatsapp_interactive_list(db: Session, entity_id: str, to_wa_id: str, body_text: str, button_label: str, sections: list[dict], sent_by_user_id: str | None = None) -> ConversationMessage:
    total_rows = sum(len(s.get("rows", [])) for s in sections)
    if not 1 <= total_rows <= 10:
        raise DomainError("An interactive list needs between 1 and 10 total options")
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    wamid = send_interactive_list_message(connection.phone_number_id, access_token, to_wa_id, body_text, button_label, sections)
    return _persist_outbound(db, entity_id, conversation, "interactive_list", body_text, None, wamid, sent_by_user_id, {"button_label": button_label, "sections": sections})


def send_whatsapp_product(db: Session, entity_id: str, to_wa_id: str, product_retailer_id: str, body_text: str | None = None, sent_by_user_id: str | None = None) -> ConversationMessage:
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    if not connection.catalog_id:
        raise DomainError("Add your Meta catalog id in Manage WhatsApp before sending product messages")
    access_token = decrypt_secret(connection.access_token_encrypted)
    wamid = send_product_message(connection.phone_number_id, access_token, to_wa_id, connection.catalog_id, product_retailer_id, body_text)
    return _persist_outbound(db, entity_id, conversation, "product", body_text, None, wamid, sent_by_user_id, {"catalog_id": connection.catalog_id, "product_retailer_id": product_retailer_id})


def send_whatsapp_product_list(db: Session, entity_id: str, to_wa_id: str, header_text: str, body_text: str, sections: list[dict], sent_by_user_id: str | None = None) -> ConversationMessage:
    total_items = sum(len(s.get("product_items", [])) for s in sections)
    if not 1 <= total_items <= 30:
        raise DomainError("A product list needs between 1 and 30 total items")
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    if not connection.catalog_id:
        raise DomainError("Add your Meta catalog id in Manage WhatsApp before sending product messages")
    access_token = decrypt_secret(connection.access_token_encrypted)
    wamid = send_product_list_message(connection.phone_number_id, access_token, to_wa_id, connection.catalog_id, header_text, body_text, sections)
    return _persist_outbound(db, entity_id, conversation, "product_list", body_text, None, wamid, sent_by_user_id, {"catalog_id": connection.catalog_id, "header_text": header_text, "sections": sections})


def send_whatsapp_reaction(db: Session, entity_id: str, to_wa_id: str, reacted_to_wamid: str, emoji: str, sent_by_user_id: str | None = None) -> ConversationMessage:
    connection, conversation = _resolve_send_target(db, entity_id, to_wa_id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    wamid = send_reaction_message(connection.phone_number_id, access_token, to_wa_id, reacted_to_wamid, emoji)
    return _persist_outbound(db, entity_id, conversation, "reaction", emoji, None, wamid, sent_by_user_id, {"emoji": emoji, "reacted_to_wamid": reacted_to_wamid})


def mark_conversation_read(db: Session, conversation: Conversation, connection: WabaConnection) -> None:
    """Best-effort: sends Meta a read receipt for the most recent inbound message so the customer
    sees the blue double-check, then stamps last_read_at regardless of whether that call
    succeeded -- an agent having actually opened the conversation is a local fact that shouldn't
    depend on Meta's API being reachable."""
    latest_inbound = db.scalar(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id, ConversationMessage.direction == "inbound")
        .order_by(ConversationMessage.created_at.desc()),
    )
    if latest_inbound and latest_inbound.meta_message_id and connection.status == "connected":
        try:
            access_token = decrypt_secret(connection.access_token_encrypted)
            send_read_receipt(connection.phone_number_id, access_token, latest_inbound.meta_message_id)
        except MetaApiError:
            pass
    conversation.last_read_at = datetime.now(timezone.utc)
