"""Razorpay Smart Collect (Virtual Accounts) -- a second, independent way to fund a customer's
account, alongside the existing Checkout flow in payments.py (never touched by this module).
Smart Collect money doesn't go into the SMS-credits Wallet directly: it funds a separate
rupee-balance TextziWallet, net of PlatformPaymentMethodConfig's flat_fee_paise, via an async
webhook rather than a synchronous client callback. TextziWallet is then spent (with an OTP
confirmation step, reusing channels.py's own API-key-action-OTP flow) on SMS credit top-up, WABA
subscription, or CRM subscription -- see the three spend endpoints at the bottom of this file.

Deliberately its own module, same "one file per distinct integration surface" convention as
crm_quotes.py/crm_sequences.py staying separate from crm.py."""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .channels import _consume_api_key_otp, _issue_api_key_otp
from .channel_billing import PERIOD_DAYS
from .database import SessionLocal, get_db
from .invoicing import create_draft_invoice, issue_invoice
from .models import BillingPlan, ChannelSubscription, Organization, PaymentOrder, RazorpayVirtualAccount, TextziWallet, TextziWalletTransaction, User, Wallet
from .schemas import (
    ApiKeyOtpResponse, BillingPlanOut, ChannelSubscriptionStatusOut, RazorpayVirtualAccountOut, RechargeResponse,
    TextziWalletOut, TextziWalletSpendPlanRequest, TextziWalletSpendSmsRequest, TextziWalletTransactionOut, WalletSpendOtpRequest,
)
from .services import (
    GST_RATE, DomainError, credit_textzi_wallet, credit_wallet, debit_textzi_wallet, get_platform_razorpay_keys,
    get_platform_razorpay_webhook_secret, payment_method_config, quote_credits, resolve_rate_card, resolve_user_entity,
)

logger = logging.getLogger("textzi.payments")

router = APIRouter(prefix="/v1/wallet/textzi", tags=["wallet"])
webhook_router = APIRouter(prefix="/v1/webhooks/razorpay", tags=["webhooks"])


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _razorpay_client(db: Session) -> razorpay.Client:
    key_id, key_secret = get_platform_razorpay_keys(db)
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Razorpay is not configured. Set it from Platform Settings > Razorpay Setting.")
    return razorpay.Client(auth=(key_id, key_secret))


def _wallet_out(wallet: TextziWallet) -> TextziWalletOut:
    return TextziWalletOut(entity_id=wallet.entity_id, balance=float(wallet.balance))


@router.get("", response_model=TextziWalletOut)
def get_textzi_wallet(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    wallet = db.get(TextziWallet, entity.id)
    return _wallet_out(wallet) if wallet else TextziWalletOut(entity_id=entity.id, balance=0)


@router.get("/transactions", response_model=list[TextziWalletTransactionOut])
def list_textzi_wallet_transactions(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    rows = db.scalars(
        select(TextziWalletTransaction).where(TextziWalletTransaction.entity_id == entity.id).order_by(TextziWalletTransaction.created_at.desc()).limit(200),
    ).all()
    return [
        TextziWalletTransactionOut(id=t.id, type=t.type, amount=float(t.amount), balance_after=float(t.balance_after), reference=t.reference, created_at=t.created_at.isoformat())
        for t in rows
    ]


@router.post("/account", response_model=RazorpayVirtualAccountOut)
def get_or_create_virtual_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not payment_method_config(db, "razorpay_smart_collect").enabled:
        raise HTTPException(status_code=422, detail="Bank transfer top-up is not available right now")
    entity = _resolve_entity(db, user)
    existing = db.get(RazorpayVirtualAccount, entity.id)
    if existing and existing.status == "active":
        return RazorpayVirtualAccountOut(account_number=existing.account_number, ifsc=existing.ifsc, status=existing.status)

    client = _razorpay_client(db)
    # Cosmetic only -- Razorpay's "notes" is a free-form key-value bag it stores and echoes back
    # as-is (no schema, nothing validated), shown on their dashboard so a payment is recognizable
    # by more than just entity_id. This does NOT enable TPV (payer-identity verification) --
    # that's a deliberately separate, unused feature (see this module's own docstring on non-TPV).
    organization = db.get(Organization, entity.organization_id)
    notes = {"entity_id": entity.id}
    if organization:
        if organization.name:
            notes["company_name"] = organization.name
        if organization.gstin:
            notes["gstin"] = organization.gstin
        if organization.contact_email:
            notes["contact_email"] = organization.contact_email
        if organization.contact_mobile:
            notes["contact_mobile"] = organization.contact_mobile
    try:
        account = client.virtual_account.create({
            # Bank rails only (IMPS/NEFT/RTGS all land on the same account_number+ifsc) --
            # deliberately no "vpa" receiver type, so no UPI ID is provisioned or shown.
            "receivers": {"types": ["bank_account"]},
            "description": f"Textzi Wallet top-up -- entity {entity.id}",
            "notes": notes,
        })
    except razorpay.errors.BadRequestError as exc:
        raise HTTPException(status_code=422, detail=f"Razorpay rejected the virtual account request: {exc}") from exc

    bank_receiver = next((r for r in account.get("receivers", []) if r.get("entity") == "bank_account"), None)

    if existing:
        existing.razorpay_account_id = account["id"]
        existing.account_number = bank_receiver.get("account_number") if bank_receiver else None
        existing.ifsc = bank_receiver.get("ifsc") if bank_receiver else None
        existing.status = "active"
        row = existing
    else:
        row = RazorpayVirtualAccount(
            entity_id=entity.id, razorpay_account_id=account["id"],
            account_number=bank_receiver.get("account_number") if bank_receiver else None,
            ifsc=bank_receiver.get("ifsc") if bank_receiver else None,
        )
        db.add(row)
    db.commit()
    return RazorpayVirtualAccountOut(account_number=row.account_number, ifsc=row.ifsc, status=row.status)


@router.post("/account/close")
def close_virtual_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Lets a customer remove their current bank-transfer account and generate a fresh one --
    e.g. if the wrong one was set up, or as a reset. Closing on Razorpay's side is best-effort:
    if Razorpay already sees it as closed (or the call otherwise fails), we still mark it closed
    locally so get_or_create_virtual_account provisions a new one on the next request, rather than
    leaving the customer stuck with a dead account they can't replace."""
    entity = _resolve_entity(db, user)
    existing = db.get(RazorpayVirtualAccount, entity.id)
    if not existing or existing.status != "active":
        raise HTTPException(status_code=422, detail="No active bank transfer account to remove")
    try:
        client = _razorpay_client(db)
        client.virtual_account.close(existing.razorpay_account_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("could not close virtual account %s on Razorpay's side: %s", existing.razorpay_account_id, exc)
    existing.status = "closed"
    db.commit()
    return {"status": "closed"}


@webhook_router.post("/smart-collect")
async def receive_smart_collect_webhook(request: Request, db: Session = Depends(get_db)):
    """Signature-verified the identical way waba_webhooks.py verifies Meta's own webhooks: HMAC-
    SHA256 over the raw body, compared with hmac.compare_digest. Always acks 200 for anything past
    signature verification -- a malformed/unrecognized event is logged and skipped, not raised,
    since a non-2xx makes Razorpay retry (and can get the webhook disabled if it keeps failing)."""
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    webhook_secret = get_platform_razorpay_webhook_secret(db)
    if not webhook_secret:
        raise HTTPException(status_code=403, detail="Smart Collect webhook is not configured on this platform")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing signature")
    expected_signature = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        logger.warning("smart collect webhook: signature mismatch")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        return {"status": "ignored", "reason": "invalid_json"}

    if payload.get("event") != "virtual_account.credited":
        return {"status": "ignored", "reason": "unhandled_event"}

    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    va_entity = payload.get("payload", {}).get("virtual_account", {}).get("entity", {})
    razorpay_payment_id = payment_entity.get("id")
    razorpay_account_id = va_entity.get("id")
    gross_paise = payment_entity.get("amount")
    if not razorpay_payment_id or not razorpay_account_id or gross_paise is None:
        logger.warning("smart collect webhook: missing required fields in payload")
        return {"status": "ignored", "reason": "missing_fields"}

    # Idempotency: Razorpay retries on non-2xx, and can deliver near-simultaneous duplicates for
    # the same payment_id -- this SELECT is a fast-path only (avoids redundant work on the common
    # case), NOT the actual correctness guarantee, since a plain check-then-act here has a real
    # race window under concurrent delivery. The real guarantee is PaymentOrder.provider_order_id's
    # DB-level unique constraint below: two concurrent credits for the same payment_id will have
    # one succeed and one hit IntegrityError, which is what actually prevents a double-credit.
    if db.scalar(select(TextziWalletTransaction).where(TextziWalletTransaction.reference == razorpay_payment_id)):
        return {"status": "ok", "reason": "already_processed"}

    virtual_account = db.scalar(select(RazorpayVirtualAccount).where(RazorpayVirtualAccount.razorpay_account_id == razorpay_account_id))
    if not virtual_account:
        logger.warning("smart collect webhook: no RazorpayVirtualAccount for razorpay_account_id=%s", razorpay_account_id)
        return {"status": "ignored", "reason": "unknown_virtual_account"}

    fee_paise = payment_method_config(db, "razorpay_smart_collect").flat_fee_paise
    net_paise = max(0, gross_paise - fee_paise)
    if net_paise == 0:
        logger.info("smart collect webhook: transfer of %s paise did not exceed the %s paise flat fee for entity_id=%s", gross_paise, fee_paise, virtual_account.entity_id)
        return {"status": "ok", "reason": "below_fee_threshold"}

    net_rupees = net_paise / 100
    wallet = credit_textzi_wallet(db, virtual_account.entity_id, net_rupees, transaction_type="smart_collect_topup", reference=razorpay_payment_id)
    db.add(PaymentOrder(entity_id=virtual_account.entity_id, provider="razorpay_smart_collect", provider_order_id=razorpay_payment_id, amount=net_rupees, purpose="textzi_wallet_topup", status="paid"))
    try:
        db.commit()
    except IntegrityError:
        # The race the SELECT above couldn't fully close: a concurrent delivery for this same
        # payment_id committed first. Roll back this attempt's credit entirely -- the other
        # request's commit is the one that actually counts -- and report success either way,
        # since from Razorpay's perspective the payment IS processed.
        db.rollback()
        logger.info("smart collect webhook: concurrent duplicate delivery for payment_id=%s, discarding this attempt's credit", razorpay_payment_id)
        return {"status": "ok", "reason": "already_processed"}
    logger.info("smart collect: credited %.2f to TextziWallet for entity_id=%s (gross=%s paise, fee=%s paise)", net_rupees, virtual_account.entity_id, gross_paise, fee_paise)
    return {"status": "ok"}


# --- Spending the Textzi Wallet (OTP-gated) --------------------------------------------------

@router.post("/spend/request-otp", response_model=ApiKeyOtpResponse)
def request_wallet_spend_otp(payload: WalletSpendOtpRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return _issue_api_key_otp(db, user, "wallet_spend")


@router.post("/spend/sms-credit", response_model=RechargeResponse)
def spend_wallet_on_sms_credit(payload: TextziWalletSpendSmsRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not payment_method_config(db, "razorpay_smart_collect").enabled:
        raise HTTPException(status_code=422, detail="Textzi Wallet payment is not available right now")
    entity = _resolve_entity(db, user)
    _consume_api_key_otp(db, user.id, "wallet_spend", payload.otp_code)

    try:
        rate_card = resolve_rate_card(db, user)
        credits, slab = quote_credits(db, rate_card, payload.amount)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    gst_amount = round(payload.amount * GST_RATE, 2)
    total = round(payload.amount + gst_amount, 2)
    try:
        debit_textzi_wallet(db, entity.id, total, transaction_type="spend_sms_credit")
        sms_wallet = credit_wallet(db, entity.id, credits, transaction_type="recharge_textzi_wallet")
        invoice = create_draft_invoice(db, entity, type="wallet_recharge", base_amount=payload.amount, gst_amount=gst_amount, reference="textzi_wallet", credits_purchased=round(credits, 2), price_per_sms=float(slab.price_per_sms))
        issue_invoice(db, invoice)
    except DomainError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()

    available = float(sms_wallet.prepaid_balance) + max(0, float(sms_wallet.credit_limit) - float(sms_wallet.credit_used))
    return RechargeResponse(entity_id=entity.id, amount=payload.amount, available_balance=available, credits_purchased=round(credits, 2), gst_amount=gst_amount, total_charged=total)


@router.post("/spend/plan/{plan_id}", response_model=ChannelSubscriptionStatusOut)
def spend_wallet_on_plan(plan_id: str, payload: TextziWalletSpendPlanRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not payment_method_config(db, "razorpay_smart_collect").enabled:
        raise HTTPException(status_code=422, detail="Textzi Wallet payment is not available right now")
    entity = _resolve_entity(db, user)
    _consume_api_key_otp(db, user.id, "wallet_spend", payload.otp_code)

    plan = db.get(BillingPlan, plan_id)
    if not plan or not plan.active:
        raise HTTPException(status_code=404, detail="Plan not found")

    gst_amount = round(float(plan.price) * GST_RATE, 2)
    total = round(float(plan.price) + gst_amount, 2)
    now = datetime.now(timezone.utc)
    try:
        debit_textzi_wallet(db, entity.id, total, transaction_type=f"spend_{plan.channel}_subscription")
        subscription = db.get(ChannelSubscription, (entity.id, plan.channel))
        if not subscription:
            subscription = ChannelSubscription(entity_id=entity.id, channel=plan.channel)
            db.add(subscription)
        start_from = subscription.period_end if subscription.period_end and subscription.period_end > now and subscription.plan_id == plan.id else now
        subscription.plan_id = plan.id
        subscription.period_start = start_from if start_from == now else (subscription.period_start or now)
        subscription.period_end = start_from + timedelta(days=PERIOD_DAYS[plan.period])
        subscription.messages_used = 0 if start_from == now else subscription.messages_used
        subscription.paid_at = now
        invoice = create_draft_invoice(db, entity, type="channel_subscription", base_amount=float(plan.price), gst_amount=gst_amount, reference="textzi_wallet")
        issue_invoice(db, invoice)
    except DomainError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(subscription)

    seats_used = db.scalar(select(func.count()).select_from(User).where(User.organization_id == user.organization_id)) or 0
    return ChannelSubscriptionStatusOut(
        channel=plan.channel, plan=_plan_out(plan), period_start=subscription.period_start.isoformat(),
        period_end=subscription.period_end.isoformat(), messages_used=subscription.messages_used, seats_used=seats_used,
    )


def _plan_out(plan: BillingPlan) -> BillingPlanOut:
    return BillingPlanOut(id=plan.id, channel=plan.channel, name=plan.name, period=plan.period, price=float(plan.price), message_limit=plan.message_limit, user_limit=plan.user_limit, active=plan.active)
