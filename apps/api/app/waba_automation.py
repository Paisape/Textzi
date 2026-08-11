"""Simple trigger -> action rules, evaluated against every inbound WhatsApp message
(waba_webhooks.py calls apply_rules right after persisting one). Deliberately NOT the WhatsApp
Flow-style guided-bot builder from the plan's Phase B -- that's a standalone product surface
(node/edge flow, a flow-builder UI) sized separately; this is the much smaller "if X then Y"
rule engine every competitor also ships as a lighter-weight complement to a real bot. Its own
module, never touching dispatch.py/providers.py/webhooks.py (the SMS-specific pipeline)."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AutomationRule, CannedResponse, Contact, Conversation, ConversationLabel
from .waba_meta import MetaApiError

logger = logging.getLogger("textzi.waba")


def apply_rules(db: Session, entity_id: str, contact: Contact, conversation: Conversation, message_body: str | None, is_new_contact: bool) -> None:
    rules = db.scalars(
        select(AutomationRule).where(AutomationRule.entity_id == entity_id, AutomationRule.active == True).order_by(AutomationRule.priority.asc()),  # noqa: E712
    ).all()
    for rule in rules:
        if not _trigger_matches(rule, message_body, is_new_contact):
            continue
        try:
            _apply_action(db, entity_id, contact, conversation, rule)
        except Exception:
            # One misconfigured rule (e.g. a canned response or label that's since been deleted)
            # must never block the inbound message itself from being saved -- that already
            # happened in the caller before apply_rules runs.
            logger.exception("waba automation: rule %s failed to apply for entity_id=%s", rule.id, entity_id)


def _trigger_matches(rule: AutomationRule, message_body: str | None, is_new_contact: bool) -> bool:
    if rule.trigger_type == "new_contact":
        return is_new_contact
    if rule.trigger_type == "keyword":
        if not rule.trigger_value or not message_body:
            return False
        return rule.trigger_value.strip().lower() in message_body.lower()
    return False


def _apply_action(db: Session, entity_id: str, contact: Contact, conversation: Conversation, rule: AutomationRule) -> None:
    if rule.action_type == "assign":
        conversation.assigned_user_id = rule.action_value
    elif rule.action_type == "label":
        if not db.get(ConversationLabel, (conversation.id, rule.action_value)):
            db.add(ConversationLabel(conversation_id=conversation.id, label_id=rule.action_value))
    elif rule.action_type == "reply":
        canned = db.get(CannedResponse, rule.action_value)
        if not canned:
            return
        # Local import -- waba_dispatch imports waba_realtime which is fine, but importing it at
        # module load time here would need waba_dispatch to not import this module back (it
        # doesn't), so this is just keeping the dependency close to its one use rather than a
        # real cycle concern.
        from .waba_dispatch import send_whatsapp_text
        try:
            send_whatsapp_text(db, entity_id, contact.wa_id, canned.body)
        except MetaApiError:
            logger.warning("waba automation: auto-reply send failed for entity_id=%s rule=%s", entity_id, rule.id)
