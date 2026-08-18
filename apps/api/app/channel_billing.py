"""Subscription-plan billing for the WABA and CRM channels -- plan catalog is admin-managed
(see admin.py's billing-plan endpoints), a customer subscribes by paying via Razorpay here, and
services.channel_active()/check_message_quota()/check_seat_quota() read the resulting
ChannelSubscription row (plan_id/period_start/period_end/messages_used) to gate usage. Mirrors
channels.py's DLT-request Razorpay flow (order -> verify, amount always computed server-side from
the plan, never trusted from the client) and payments.py's own wallet-recharge flow -- same
signature-verification and independently-refetched-payment-amount checks, just a different effect
applied on success."""
from datetime import datetime, timedelta, timezone

import razorpay
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_user
from .config import settings
from .database import get_db
from .invoicing import create_draft_invoice, issue_invoice
from .models import BillingPlan, ChannelSubscription, Entity, PaymentOrder, User
from .schemas import BillingPlanOut, ChannelSubscriptionStatusOut, PlanOrderRequest, RazorpayOrderResponse, RazorpayVerifyRequest
from .services import GST_RATE, DomainError, expected_order_paise, flag_suspicious_payment, get_platform_razorpay_keys, resolve_user_entity

router = APIRouter(prefix="/v1/billing", tags=["billing"])

PERIOD_DAYS = {"monthly": 30, "quarterly": 90, "yearly": 365}


def _razorpay_client(db: Session) -> tuple[razorpay.Client, str]:
    key_id, key_secret = get_platform_razorpay_keys(db)
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Razorpay is not configured. Set it from Platform Settings > Razorpay Setting, or RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET in .env.")
    return razorpay.Client(auth=(key_id, key_secret)), key_id


def _plan_out(plan: BillingPlan) -> BillingPlanOut:
    return BillingPlanOut(
        id=plan.id, channel=plan.channel, name=plan.name, period=plan.period, price=float(plan.price),
        message_limit=plan.message_limit, user_limit=plan.user_limit, active=plan.active,
    )


def _resolve_entity(db: Session, user: User) -> Entity:
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plans", response_model=list[BillingPlanOut])
def list_plans(channel: str, db: Session = Depends(get_db)):
    if channel not in ("waba", "crm"):
        raise HTTPException(status_code=422, detail="Unknown channel")
    plans = db.scalars(select(BillingPlan).where(BillingPlan.channel == channel, BillingPlan.active.is_(True)).order_by(BillingPlan.price.asc())).all()
    return [_plan_out(p) for p in plans]


@router.get("/subscription", response_model=ChannelSubscriptionStatusOut)
def get_subscription(channel: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if channel not in ("waba", "crm"):
        raise HTTPException(status_code=422, detail="Unknown channel")
    entity = _resolve_entity(db, user)
    subscription = db.get(ChannelSubscription, (entity.id, channel))
    plan = db.get(BillingPlan, subscription.plan_id) if subscription and subscription.plan_id else None
    seats_used = db.scalar(select(func.count()).select_from(User).where(User.organization_id == user.organization_id)) or 0
    return ChannelSubscriptionStatusOut(
        channel=channel, plan=_plan_out(plan) if plan else None,
        period_start=subscription.period_start.isoformat() if subscription and subscription.period_start else None,
        period_end=subscription.period_end.isoformat() if subscription and subscription.period_end else None,
        messages_used=subscription.messages_used if subscription else 0,
        seats_used=seats_used,
    )


@router.post("/razorpay/order", response_model=RazorpayOrderResponse)
def create_plan_order(payload: PlanOrderRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    client, key_id = _razorpay_client(db)
    entity = _resolve_entity(db, user)
    plan = db.get(BillingPlan, payload.plan_id)
    if not plan or not plan.active:
        raise HTTPException(status_code=404, detail="Plan not found")
    # plan.price is pre-tax (same convention as every other Razorpay flow in this codebase --
    # payments.create_order, channels.create_dlt_request_order) -- GST is added on top at
    # checkout, and expected_order_paise() independently re-derives this same GST-inclusive
    # amount at verify time from order.amount, so the two must stay in lockstep.
    amount_paise = int(round(float(plan.price) * (1 + GST_RATE) * 100))
    try:
        # Razorpay caps "receipt" at 40 characters -- same constraint hit in payments.py and
        # channels.py, same fix (short prefix, full ids in "notes" instead).
        order = client.order.create({"amount": amount_paise, "currency": "INR", "receipt": f"p-{entity.id[:20]}", "notes": {"entity_id": entity.id, "plan_id": plan.id, "channel": plan.channel}})
    except razorpay.errors.BadRequestError as exc:
        raise HTTPException(status_code=422, detail=f"Razorpay rejected the order request: {exc}") from exc
    db.add(PaymentOrder(entity_id=entity.id, provider="razorpay", provider_order_id=order["id"], amount=plan.price, purpose="channel_subscription", reference_id=plan.id, status="created", user_id=user.id))
    db.commit()
    return RazorpayOrderResponse(order_id=order["id"], key_id=key_id, amount_paise=amount_paise)


@router.post("/razorpay/verify", response_model=ChannelSubscriptionStatusOut)
def verify_plan_payment(payload: RazorpayVerifyRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    client, _ = _razorpay_client(db)
    entity = _resolve_entity(db, user)

    order = db.scalar(select(PaymentOrder).where(PaymentOrder.provider_order_id == payload.razorpay_order_id, PaymentOrder.entity_id == entity.id).with_for_update())
    if not order or order.purpose != "channel_subscription":
        raise HTTPException(status_code=404, detail="No matching payment order for this account")
    if order.status != "created":
        raise HTTPException(status_code=409, detail=f"This order has already been {order.status}")

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": payload.razorpay_order_id,
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_signature": payload.razorpay_signature,
        })
    except razorpay.errors.SignatureVerificationError as exc:
        order.status = "failed"
        db.commit()
        raise HTTPException(status_code=422, detail="Payment signature verification failed") from exc

    try:
        razorpay_payment = client.payment.fetch(payload.razorpay_payment_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not confirm this payment with Razorpay right now. Please try again in a moment.") from exc
    expected_paise = expected_order_paise(order)
    if razorpay_payment.get("status") != "captured" or razorpay_payment.get("amount") != expected_paise:
        flag_suspicious_payment(
            db, order, entity,
            f"expected {expected_paise} paise captured, Razorpay reports status={razorpay_payment.get('status')} amount={razorpay_payment.get('amount')}",
            user=user,
        )
        db.commit()
        raise HTTPException(status_code=422, detail=f"We couldn't automatically confirm this payment. It's been flagged for manual review -- contact support with reference {order.id} if this is urgent.")

    plan = db.get(BillingPlan, order.reference_id)
    if not plan:
        raise HTTPException(status_code=404, detail="This plan no longer exists")

    now = datetime.now(timezone.utc)
    subscription = db.get(ChannelSubscription, (entity.id, plan.channel))
    if not subscription:
        subscription = ChannelSubscription(entity_id=entity.id, channel=plan.channel)
        db.add(subscription)
    # A renewal on the same plan extends from the current period_end if it hasn't lapsed yet
    # (buying early doesn't waste the remaining days); anything else (first purchase, a lapsed
    # plan, or switching plans) starts a fresh period from now.
    start_from = subscription.period_end if subscription.period_end and subscription.period_end > now and subscription.plan_id == plan.id else now
    subscription.plan_id = plan.id
    subscription.period_start = start_from if start_from == now else (subscription.period_start or now)
    subscription.period_end = start_from + timedelta(days=PERIOD_DAYS[plan.period])
    subscription.messages_used = 0 if start_from == now else subscription.messages_used
    subscription.paid_at = now

    order.status = "paid"
    gst_amount = round(float(plan.price) * GST_RATE, 2)
    invoice = create_draft_invoice(db, entity, type="channel_subscription", base_amount=float(plan.price), gst_amount=gst_amount, reference=order.id)
    issue_invoice(db, invoice)
    db.commit()
    db.refresh(subscription)

    seats_used = db.scalar(select(func.count()).select_from(User).where(User.organization_id == user.organization_id)) or 0
    return ChannelSubscriptionStatusOut(
        channel=plan.channel, plan=_plan_out(plan), period_start=subscription.period_start.isoformat(),
        period_end=subscription.period_end.isoformat(), messages_used=subscription.messages_used, seats_used=seats_used,
    )
