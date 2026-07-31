"""Read-only reporting for a logged-in customer: Wallet Ledger (every credit/debit, both
channels), Payment Ledger (every payment-gateway order attempt, whatever its outcome), Purchase
Ledger (only successful recharges -- rupees paid, credits received, rate applied), and Activity
Log (org-wide login/security events). Wallet/Payment ledgers require no special capability,
matching GET /v1/wallet's own visibility; Purchase Ledger reuses invoices:view since it's sourced
from the same Invoice rows the Invoices page already shows; Activity Log is gated by the new
activity:view capability, which -- unlike team:view/invoices:view -- is account-owner-only (see
services.ROLE_CAPABILITIES)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import AccountActivity, ApiLog, Invoice, PaymentOrder, User, WalletTransaction
from .permissions import require_capability
from .schemas import ActivityLogEntryOut, ApiLogEntryOut, PaymentLedgerEntryOut, PurchaseLedgerEntryOut, WalletLedgerEntryOut
from .services import DomainError, resolve_user_entity

router = APIRouter(prefix="/v1/reports", tags=["reports"])

LEDGER_LIMIT = 200


@router.get("/wallet-ledger", response_model=list[WalletLedgerEntryOut])
def wallet_ledger(channel: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stmt = select(WalletTransaction).where(WalletTransaction.entity_id == entity.id)
    if channel:
        stmt = stmt.where(WalletTransaction.channel == channel)
    rows = db.scalars(stmt.order_by(WalletTransaction.created_at.desc()).limit(LEDGER_LIMIT)).all()
    return [
        WalletLedgerEntryOut(
            id=t.id, channel=t.channel, type=t.type, amount=float(t.amount),
            # No stored balance_before column -- amount is signed (+credit/-debit) against the
            # same balance_after, so subtracting it back out reconstructs the pre-transaction
            # balance exactly, without needing a schema change or a self-join to the prior row.
            balance_before=float(t.balance_after) - float(t.amount), balance_after=float(t.balance_after),
            reference=t.reference, created_at=t.created_at.isoformat(),
        )
        for t in rows
    ]


@router.get("/payment-ledger", response_model=list[PaymentLedgerEntryOut])
def payment_ledger(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = db.scalars(
        select(PaymentOrder).where(PaymentOrder.entity_id == entity.id).order_by(PaymentOrder.created_at.desc()).limit(LEDGER_LIMIT),
    ).all()
    return [
        PaymentLedgerEntryOut(id=o.id, provider=o.provider, provider_order_id=o.provider_order_id, purpose=o.purpose, amount=float(o.amount), status=o.status, created_at=o.created_at.isoformat())
        for o in rows
    ]


@router.get("/purchase-ledger", response_model=list[PurchaseLedgerEntryOut])
def purchase_ledger(user: User = Depends(require_capability("invoices:view")), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = db.scalars(
        select(Invoice)
        .where(Invoice.entity_id == entity.id, Invoice.type == "wallet_recharge", Invoice.status == "issued")
        .order_by(Invoice.issued_at.desc())
        .limit(LEDGER_LIMIT),
    ).all()
    return [
        PurchaseLedgerEntryOut(
            id=i.id, invoice_number=i.invoice_number, base_amount=float(i.base_amount), gst_amount=float(i.gst_amount),
            total_amount=float(i.total_amount), credits_purchased=float(i.credits_purchased) if i.credits_purchased is not None else None,
            price_per_sms=float(i.price_per_sms) if i.price_per_sms is not None else None, created_at=(i.issued_at or i.created_at).isoformat(),
        )
        for i in rows
    ]


@router.get("/activity-log", response_model=list[ActivityLogEntryOut])
def activity_log(user: User = Depends(require_capability("activity:view")), db: Session = Depends(get_db)):
    if not user.organization_id:
        raise HTTPException(status_code=422, detail="Complete organisation onboarding first")
    rows = db.scalars(
        select(AccountActivity).where(AccountActivity.organization_id == user.organization_id).order_by(AccountActivity.created_at.desc()).limit(LEDGER_LIMIT),
    ).all()
    return [
        ActivityLogEntryOut(id=a.id, event_type=a.event_type, description=a.description, actor_email=a.actor_email, ip_address=a.ip_address, created_at=a.created_at.isoformat())
        for a in rows
    ]


@router.get("/api-log", response_model=list[ApiLogEntryOut])
def api_log(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = db.scalars(
        select(ApiLog).where(ApiLog.entity_id == entity.id).order_by(ApiLog.created_at.desc()).limit(LEDGER_LIMIT),
    ).all()
    return [
        ApiLogEntryOut(
            id=a.id, endpoint=a.endpoint, method=a.metadata_json.get("method"), status_code=a.status_code,
            latency_ms=a.latency_ms, error=a.metadata_json.get("error"), created_at=a.created_at.isoformat(),
        )
        for a in rows
    ]
