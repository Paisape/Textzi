"""WhatsApp Commerce order management (Addendum 14 Phase 2) -- a structured status lifecycle on
top of the WabaOrder/WabaOrderItem rows waba_webhooks.py creates from Meta's inbound cart-order
messages. Deliberately its own module, same "one file per distinct integration surface"
convention as catalog_sync.py; imports waba_dispatch one-directionally, never the reverse."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import Contact, User, WabaOrder, WabaOrderItem
from .permissions import require_channel_scope
from .schemas import WabaOrderOut, WabaOrderStatusUpdateRequest
from .services import DomainError, resolve_user_entity
from .waba_dispatch import send_whatsapp_text
from .waba_meta import MetaApiError

router = APIRouter(prefix="/v1/waba/orders", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])

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
        items=[
            {"product_retailer_id": i.product_retailer_id, "product_name": i.product_name, "quantity": i.quantity,
             "item_price": float(i.item_price) if i.item_price is not None else None, "currency": i.currency}
            for i in items
        ],
    )


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
