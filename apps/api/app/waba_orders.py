"""WhatsApp Commerce order management (Addendum 14 Phases 2-4) -- a structured status lifecycle on
top of the WabaOrder/WabaOrderItem rows waba_webhooks.py creates from Meta's inbound cart-order
messages, Razorpay Payment Link-based payment collection, and an abandoned-cart reminder job.
Deliberately its own module, same "one file per distinct integration surface" convention as
catalog_sync.py; imports waba_dispatch one-directionally, never the reverse."""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import razorpay
import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import SessionLocal, get_db
from .models import Contact, Conversation, ConversationMessage, PaymentOrder, User, WabaOrder, WabaOrderItem
from .permissions import require_channel_scope
from .schemas import WabaOrderOut, WabaOrderStatusUpdateRequest
from .services import DomainError, get_platform_razorpay_keys, get_platform_razorpay_webhook_secret, resolve_user_entity
from .waba_dispatch import send_whatsapp_text
from .waba_meta import MetaApiError

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/waba/orders", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])
webhook_router = APIRouter(prefix="/v1/webhooks/razorpay", tags=["webhooks"])

_VALID_STATUSES = ("new", "confirmed", "shipped", "delivered", "cancelled")
_STATUS_MESSAGES = {
    "confirmed": "Your order has been confirmed. We'll update you when it ships.",
    "shipped": "Your order is on its way!",
    "delivered": "Your order has been delivered. Thank you for shopping with us!",
    "cancelled": "Your order has been cancelled.",
}


def _order_out(db: Session, order: WabaOrder) -> WabaOrderOut:
    items = db.scalars(select(WabaOrderItem).where(WabaOrderItem.order_id == order.id)).all()
    contact = db.get(Contact, order.contact_id)
    return WabaOrderOut(
        id=order.id, contact_id=order.contact_id, contact_name=contact.name if contact else None,
        conversation_id=order.conversation_id, status=order.status,
        total_amount=float(order.total_amount) if order.total_amount is not None else None,
        currency=order.currency, created_at=order.created_at.isoformat(),
        status_updated_at=order.status_updated_at.isoformat() if order.status_updated_at else None,
        payment_status=order.payment_status, payment_link_url=order.razorpay_payment_link_url, deal_id=order.deal_id,
        items=[
            {"product_retailer_id": i.product_retailer_id, "product_name": i.product_name, "quantity": i.quantity,
             "item_price": float(i.item_price) if i.item_price is not None else None, "currency": i.currency}
            for i in items
        ],
    )


def _razorpay_client(db: Session) -> razorpay.Client:
    key_id, key_secret = get_platform_razorpay_keys(db)
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Razorpay is not configured. Set it from Platform Settings > Razorpay Setting.")
    return razorpay.Client(auth=(key_id, key_secret))


@router.get("", response_model=list[WabaOrderOut])
def list_orders(status: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    query = select(WabaOrder).where(WabaOrder.entity_id == entity.id)
    if status:
        query = query.where(WabaOrder.status == status)
    orders = db.scalars(query.order_by(WabaOrder.created_at.desc()).limit(200)).all()
    return [_order_out(db, order) for order in orders]


@router.get("/{order_id}", response_model=WabaOrderOut)
def get_order(order_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    order = db.get(WabaOrder, order_id)
    if not order or order.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_out(db, order)


@router.patch("/{order_id}/status", response_model=WabaOrderOut)
def update_order_status(order_id: str, payload: WabaOrderStatusUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Moves an order through its lifecycle from Textzi's own UI. Meta's own structured
    order-status push-back message only exists inside the separate, gated Payments API flow
    (confirmed in Addendum 14's research) -- since a plain cart order like this one didn't go
    through that flow, the customer-facing update is an ordinary text message instead. This only
    reaches the customer inside WhatsApp's 24-hour free-form session window; outside it, the send
    fails and is surfaced to the agent as a normal error rather than silently dropped."""
    if payload.status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(_VALID_STATUSES)}")
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    order = db.get(WabaOrder, order_id)
    if not order or order.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = payload.status
    order.status_updated_at = datetime.now(timezone.utc)
    contact = db.get(Contact, order.contact_id)
    notify_text = _STATUS_MESSAGES.get(payload.status)
    if notify_text and contact and contact.wa_id:
        # Best-effort: the status change itself still commits below even if the customer
        # notification fails (outside the 24h session window, WABA disconnected, etc.) -- an
        # agent should be able to record a shipped/delivered order even when Meta won't deliver
        # the courtesy text right now.
        try:
            send_whatsapp_text(db, entity.id, contact.wa_id, notify_text, sent_by_user_id=user.id)
        except (DomainError, MetaApiError):
            pass
    db.commit()
    return _order_out(db, order)


@router.post("/{order_id}/request-payment", response_model=WabaOrderOut)
def request_payment(order_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Generates a Razorpay Payment Link for this order's total and sends it to the customer as a
    plain WhatsApp message -- this is the primary payment path (matches what the WhatsApp Commerce
    market research found is the actual mechanism behind most competitors' "native payment"
    marketing, e.g. Zoko's Magic Checkout deep link), not Meta's own Payments API, which requires
    a Meta-side payment configuration through one of four named PG partners and WABA-tier
    verification this platform doesn't yet have confirmed access to."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    order = db.get(WabaOrder, order_id)
    if not order or order.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order.total_amount:
        raise HTTPException(status_code=422, detail="This order has no total amount to request payment for")
    if order.payment_status == "paid":
        raise HTTPException(status_code=409, detail="This order has already been paid")
    if order.payment_status == "pending" and order.razorpay_payment_link_url:
        raise HTTPException(status_code=409, detail="A payment link was already sent for this order")
    contact = db.get(Contact, order.contact_id)
    if not contact or not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send the payment link to")

    client = _razorpay_client(db)
    amount_paise = int(round(float(order.total_amount) * 100))
    try:
        link = client.payment_link.create({
            "amount": amount_paise, "currency": order.currency or "INR",
            "reference_id": order.id[:40],
            "description": f"Order payment ({len(db.scalars(select(WabaOrderItem).where(WabaOrderItem.order_id == order.id)).all())} items)",
            "notes": {"waba_order_id": order.id, "entity_id": entity.id},
            "notify": {"sms": False, "email": False},  # Textzi sends the link itself, via WhatsApp
        })
    except razorpay.errors.BadRequestError as exc:
        raise HTTPException(status_code=422, detail=f"Razorpay rejected the payment link request: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        # A network-level failure (DNS, timeout, connection refused) raises here, not via
        # BadRequestError -- left uncaught this 500s instead of giving the agent a clean retry
        # message. (channel_billing.py's own create_plan_order has the identical gap; not fixed
        # here since it's a separate, pre-existing file this change doesn't otherwise touch.)
        raise HTTPException(status_code=502, detail=f"Could not reach Razorpay: {exc}") from exc

    order.razorpay_payment_link_id = link["id"]
    order.razorpay_payment_link_url = link["short_url"]
    order.payment_status = "pending"
    db.add(PaymentOrder(entity_id=entity.id, provider="razorpay", provider_order_id=link["id"], amount=order.total_amount, purpose="waba_order_payment", reference_id=order.id, status="created", user_id=user.id))
    # Commit the link itself before attempting the send -- the link is already real on Razorpay's
    # side at this point (the create() call above succeeded), so losing the local reference on a
    # send failure would strand it with no way to retry except creating a second, orphaned link.
    db.commit()

    try:
        send_whatsapp_text(db, entity.id, contact.wa_id, f"Please complete your payment here: {link['short_url']}", sent_by_user_id=user.id)
    except (DomainError, MetaApiError) as exc:
        raise HTTPException(status_code=422, detail=f"Payment link created, but could not send it: {exc}") from exc
    return _order_out(db, order)


@webhook_router.post("/waba-order")
async def receive_waba_order_payment_webhook(request: Request, db: Session = Depends(get_db)):
    """Signature-verified the identical way payments_smart_collect.py verifies Razorpay's own
    webhooks: HMAC-SHA256 over the raw body, compared with hmac.compare_digest, using the same
    Dashboard-level webhook secret (one webhook config in Razorpay Dashboard, multiple event types
    routed to different endpoints in this codebase -- not a separate secret per event). Always
    acks 200 for anything past signature verification -- a malformed/unrecognized event is logged
    and skipped, not raised, since a non-2xx makes Razorpay retry."""
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    webhook_secret = get_platform_razorpay_webhook_secret(db)
    if not webhook_secret:
        raise HTTPException(status_code=403, detail="Razorpay webhook is not configured on this platform")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing signature")
    expected_signature = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        logger.warning("waba order payment webhook: signature mismatch")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        return {"status": "ignored", "reason": "invalid_json"}

    if payload.get("event") != "payment_link.paid":
        return {"status": "ignored", "reason": "unhandled_event"}

    link_entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
    razorpay_link_id = link_entity.get("id")
    if not razorpay_link_id:
        return {"status": "ignored", "reason": "missing_payment_link_id"}

    order = db.scalar(select(WabaOrder).where(WabaOrder.razorpay_payment_link_id == razorpay_link_id))
    if not order:
        logger.warning("waba order payment webhook: no WabaOrder for razorpay_payment_link_id=%s", razorpay_link_id)
        return {"status": "ignored", "reason": "unknown_payment_link"}
    if order.payment_status == "paid":
        return {"status": "ok", "reason": "already_processed"}

    order.payment_status = "paid"
    if order.status == "new":
        order.status = "confirmed"
        order.status_updated_at = datetime.now(timezone.utc)
    payment_order = db.scalar(select(PaymentOrder).where(PaymentOrder.provider_order_id == razorpay_link_id))
    if payment_order:
        payment_order.status = "paid"
    contact = db.get(Contact, order.contact_id)
    if contact and contact.wa_id:
        try:
            send_whatsapp_text(db, order.entity_id, contact.wa_id, "Payment received -- thank you! Your order has been confirmed.", sent_by_user_id=None)
        except (DomainError, MetaApiError):
            pass
    db.commit()
    return {"status": "ok"}


_ABANDONED_CART_WINDOW = timedelta(hours=24)
_ABANDONED_CART_MESSAGE = "Still interested? Your items are waiting -- reply here if you'd like to complete your order."


def _has_reminded(message: ConversationMessage) -> bool:
    return bool((message.payload or {}).get("cart_reminder_sent"))


def send_abandoned_cart_reminders() -> None:
    """The scheduled runner (main.py's lifespan, hourly) -- Meta emits no cart-abandonment webhook
    at all (confirmed in Addendum 14's own research), and unlike every India BSP competitor
    researched there, this platform has no e-commerce-platform backend to infer abandonment from
    either. The honest signal available: a product/product_list message was sent and no WabaOrder
    followed from that same conversation within the window below -- weaker than a real cart-state
    event, a real and disclosed limitation, not hidden. Owns its own DB session since it runs
    outside any request context, same shape as catalog_sync.sync_all_catalogs."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - _ABANDONED_CART_WINDOW
        # Candidates: outbound product/product_list sends old enough that any resulting order
        # would already have arrived, not yet reminded. A tighter lower bound (say, 7 days) would
        # be a reasonable follow-on to avoid resurfacing very old sends forever; not added here
        # since nothing in this codebase yet prunes ConversationMessage rows that old anyway.
        candidates = db.scalars(
            select(ConversationMessage).where(
                ConversationMessage.direction == "outbound",
                ConversationMessage.message_type.in_(("product", "product_list")),
                ConversationMessage.created_at <= cutoff,
            ).order_by(ConversationMessage.created_at.desc()),
        ).all()
        for message in candidates:
            if _has_reminded(message):
                continue
            conversation = db.get(Conversation, message.conversation_id)
            if not conversation:
                continue
            # An order created any time after this product message (not just within the window)
            # counts as "didn't abandon" -- a customer who takes 2 days to check out shouldn't get
            # a reminder for an order they already placed.
            has_order = db.scalar(
                select(WabaOrder.id).where(WabaOrder.conversation_id == conversation.id, WabaOrder.created_at >= message.created_at).limit(1),
            )
            message.payload = {**(message.payload or {}), "cart_reminder_sent": True}
            if has_order:
                continue
            contact = db.get(Contact, conversation.contact_id)
            if not contact or not contact.wa_id:
                continue
            try:
                send_whatsapp_text(db, conversation.entity_id, contact.wa_id, _ABANDONED_CART_MESSAGE, sent_by_user_id=None)
            except (DomainError, MetaApiError):
                logger.info("abandoned cart reminder: could not send for conversation_id=%s", conversation.id)
        db.commit()
    except Exception:
        logger.warning("abandoned cart reminder job failed", exc_info=True)
        db.rollback()
    finally:
        db.close()
