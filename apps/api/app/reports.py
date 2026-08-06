"""Read-only reporting for a logged-in customer: Wallet Ledger (every credit/debit, both
channels), Payment Ledger (every payment-gateway order attempt, whatever its outcome), Purchase
Ledger (only successful recharges -- rupees paid, credits received, rate applied), and Activity
Log (org-wide login/security events). Wallet/Payment ledgers require no special capability,
matching GET /v1/wallet's own visibility; Purchase Ledger reuses invoices:view since it's sourced
from the same Invoice rows the Invoices page already shows; Activity Log is gated by the new
activity:view capability, which -- unlike team:view/invoices:view -- is account-owner-only (see
services.ROLE_CAPABILITIES)."""
from datetime import datetime, time, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Response
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import AccountActivity, ApiLog, DeliveryAttempt, Invoice, Message, PaymentOrder, User, WalletTransaction
from .permissions import require_capability
from .schemas import ActivityLogEntryOut, ApiLogEntryOut, PaymentLedgerEntryOut, PurchaseLedgerEntryOut, WalletLedgerEntryOut
from .security import decrypt_recipient_lenient
from .services import DomainError, mask_mobile, resolve_user_entity

router = APIRouter(prefix="/v1/reports", tags=["reports"])

LEDGER_LIMIT = 200
EXPORT_MAX_RANGE_DAYS = 366


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
        ActivityLogEntryOut(id=a.id, event_type=a.event_type, description=a.description, actor_email=a.actor_email, ip_address=a.ip_address, user_agent=a.user_agent, created_at=a.created_at.isoformat())
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


@router.get("/messages/export")
def export_messages(date_from: str, date_to: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Downloadable XLSX for any date range, including dates past the archiving cutoff --
    archiving.py only ever clears the heavy per-attempt JSON/text telemetry columns, never the
    reporting fields this pulls from (recipient, body, status, route, credits, delivery outcome),
    so this always reads straight from Postgres regardless of how old the range is, no archive
    read needed. Scoped to the caller's own entity -- never any other customer's data, same as
    every other endpoint in this router."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        start = datetime.combine(datetime.strptime(date_from, "%Y-%m-%d").date(), time.min, tzinfo=timezone.utc)
        end = datetime.combine(datetime.strptime(date_to, "%Y-%m-%d").date(), time.max, tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date_from/date_to must be in YYYY-MM-DD format") from exc
    if end < start:
        raise HTTPException(status_code=422, detail="date_to must be on or after date_from")
    if (end - start).days > EXPORT_MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Date range cannot exceed {EXPORT_MAX_RANGE_DAYS} days")

    messages = db.scalars(
        select(Message).where(Message.entity_id == entity.id, Message.created_at >= start, Message.created_at <= end).order_by(Message.created_at),
    ).all()
    message_ids = [m.id for m in messages]
    last_attempt_by_message: dict[str, DeliveryAttempt] = {}
    if message_ids:
        for a in db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.message_id.in_(message_ids)).order_by(DeliveryAttempt.created_at)).all():
            last_attempt_by_message[a.message_id] = a  # last write per message_id wins -- rows arrive in created_at order

    wb = Workbook()
    ws = wb.active
    ws.title = "Messages"
    ws.append(["Recipient", "Message", "Status", "Route", "Credits Charged", "Delivery Status Code", "Delivery Error", "Delivered At", "Sent At"])
    for m in messages:
        attempt = last_attempt_by_message.get(m.id)
        recipient = mask_mobile(decrypt_recipient_lenient(m.recipient)) if m.is_encrypted else m.recipient
        body = "[Encrypted]" if m.is_encrypted else m.rendered_body
        ws.append([
            recipient, body, m.status, m.route or "", m.credits_charged,
            attempt.delivery_status_code if attempt else None, attempt.error if attempt else None,
            attempt.delivered_at.replace(tzinfo=None) if attempt and attempt.delivered_at else None,
            m.created_at.replace(tzinfo=None),
        ])
    for column_cells in ws.columns:
        ws.column_dimensions[column_cells[0].column_letter].width = 20

    buffer = BytesIO()
    wb.save(buffer)
    filename = f"Textzi-Messages-{date_from}-to-{date_to}.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
