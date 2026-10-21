"""Wallet & Billing for the logged-in user's entity. No real payment gateway is integrated yet
(the PRD calls for Razorpay/Cashfree/PayU/PhonePe/Paytm/CCAvenue adapters) -- recharge is
self-service and instant, clearly labelled as a development-only stand-in, matching the same
honesty pattern as the simulated SMS provider and the dev-mode-only OTP echo."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .config import settings
from .database import get_db
from .invoicing import create_draft_invoice, issue_invoice
from .models import PlatformPaymentMethodConfig, User, Wallet, WalletTransaction
from .permissions import require_capability
from .schemas import PaymentMethodConfigOut, RateCardSlabOut, RateCardSummary, RechargeRequest, RechargeResponse, WalletQuoteRequest, WalletQuoteResponse, WalletResponse, WalletTransactionOut
from .services import DomainError, credit_wallet, get_gst_rate, payment_method_config, quote_credits, rate_card_slabs, require_channel_active, require_min_recharge, resolve_rate_card, resolve_user_entity

router = APIRouter(prefix="/v1/wallet", tags=["wallet"])

_PAYMENT_METHODS = ("razorpay_checkout", "razorpay_smart_collect", "bank_transfer")


@router.get("/payment-methods", response_model=list[PaymentMethodConfigOut])
def list_payment_methods_for_customer(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Read-only, any logged-in user -- unlike /v1/admin/payment-methods (which also exposes
    editing), this just tells a customer's own checkout UI which methods are currently offered."""
    return [
        PaymentMethodConfigOut(payment_method=method, enabled=payment_method_config(db, method).enabled, flat_fee_paise=payment_method_config(db, method).flat_fee_paise)
        for method in _PAYMENT_METHODS
    ]


def _require_dev_recharge() -> None:
    """This self-service recharge path skips real payment collection entirely (see module
    docstring) -- fine in development, but reachable by any customer with wallet:recharge in a
    real deployment unless explicitly blocked here. The real path is the Razorpay flow in
    payments.py (/v1/wallet/recharge/razorpay/order + /verify)."""
    if settings.environment != "development":
        raise HTTPException(status_code=403, detail="Self-service recharge is a development-only stand-in; use the Razorpay checkout flow instead.")


@router.get("", response_model=WalletResponse)
def get_wallet(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    wallet = db.get(Wallet, entity.id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet is not configured")
    transactions = db.scalars(
        select(WalletTransaction)
        .where(WalletTransaction.entity_id == entity.id, WalletTransaction.channel == "sms")
        .order_by(WalletTransaction.created_at.desc())
        .limit(50),
    ).all()
    return WalletResponse(
        entity_id=entity.id,
        prepaid_balance=float(wallet.prepaid_balance),
        credit_limit=float(wallet.credit_limit),
        credit_used=float(wallet.credit_used),
        available_balance=float(wallet.prepaid_balance) + max(0, float(wallet.credit_limit) - float(wallet.credit_used)),
        transactions=[WalletTransactionOut(id=t.id, type=t.type, amount=float(t.amount), balance_after=float(t.balance_after), reference=t.reference, created_at=t.created_at.isoformat()) for t in transactions],
        dev_recharge_available=settings.environment == "development",
    )


@router.get("/rate-card", response_model=RateCardSummary)
def get_my_rate_card(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The resolved rate card for the caller (their assignment, or the default) -- used by the
    Add Credits dialog to show the correct minimum top-up before the user even enters an amount."""
    try:
        rate_card = resolve_rate_card(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    slabs = rate_card_slabs(db, rate_card.id)
    return RateCardSummary(
        name=rate_card.name,
        min_recharge_amount=float(rate_card.min_recharge_amount),
        slabs=[RateCardSlabOut(id=s.id, min_amount=float(s.min_amount), max_amount=float(s.max_amount) if s.max_amount is not None else None, price_per_sms=float(s.price_per_sms)) for s in slabs],
    )


@router.post("/quote", response_model=WalletQuoteResponse)
def quote_recharge(payload: WalletQuoteRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """How many SMS credits a given rupee amount would buy under the caller's rate card --
    pure calculation, no wallet mutation. Backs the live preview in the Add Credits dialog."""
    try:
        entity = resolve_user_entity(db, user)
        require_channel_active(db, entity.id, "sms")
        rate_card = resolve_rate_card(db, user)
        require_min_recharge(rate_card, payload.amount)
        credits, slab = quote_credits(db, rate_card, payload.amount)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    gst_amount = round(payload.amount * get_gst_rate(db), 2)
    return WalletQuoteResponse(
        amount=payload.amount,
        gst_amount=gst_amount,
        total_amount=round(payload.amount + gst_amount, 2),
        credits=round(credits, 2),
        price_per_sms=float(slab.price_per_sms),
        rate_card_name=rate_card.name,
        min_recharge_amount=float(rate_card.min_recharge_amount),
        dev_recharge_available=settings.environment == "development",
    )


@router.post("/recharge", response_model=RechargeResponse)
def recharge_wallet(payload: RechargeRequest, user: User = Depends(require_capability("wallet:recharge")), db: Session = Depends(get_db)):
    """Development-mode simulated recharge for the SMS wallet -- converts the entered rupee
    amount into SMS credits via the caller's rate card (GST is charged but doesn't buy credits,
    matching how the real Razorpay path works in payments.py)."""
    _require_dev_recharge()
    try:
        entity = resolve_user_entity(db, user)
        require_channel_active(db, entity.id, "sms")
        rate_card = resolve_rate_card(db, user)
        require_min_recharge(rate_card, payload.amount)
        credits, slab = quote_credits(db, rate_card, payload.amount)
        wallet = credit_wallet(db, entity.id, credits, transaction_type="recharge", reference=f"self-service recharge (Rs.{payload.amount} @ Rs.{slab.price_per_sms}/sms)", channel="sms")
        gst_amount = round(payload.amount * get_gst_rate(db), 2)
        invoice = create_draft_invoice(db, entity, type="wallet_recharge", base_amount=payload.amount, gst_amount=gst_amount, credits_purchased=round(credits, 2), price_per_sms=float(slab.price_per_sms))
        issue_invoice(db, invoice)
    except DomainError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    available = float(wallet.prepaid_balance) + max(0, float(wallet.credit_limit) - float(wallet.credit_used))
    return RechargeResponse(
        entity_id=entity.id,
        amount=payload.amount,
        available_balance=available,
        credits_purchased=round(credits, 2),
        gst_amount=gst_amount,
        total_charged=round(payload.amount + gst_amount, 2),
        dev_note="Development mode — no payment gateway configured; this credited your wallet directly." if settings.environment == "development" else None,
    )
