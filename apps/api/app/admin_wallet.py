"""Admin-side Textzi Wallet management (Addendum 15) -- the bank-transfer-request review queue,
plus a standalone manual credit/debit tool for the same wallet. Both the approval action here and
the standalone adjustment call the identical services.credit_textzi_wallet_manual/debit_textzi_wallet
functions, so there is exactly one code path for "an admin put money into a Textzi Wallet by hand,"
not two that could drift apart. Deliberately its own module rather than folded into admin.py --
admin.py's own SMS-wallet credit/debit endpoints are the closest precedent this mirrors, but this
is a genuinely separate wallet with its own review-queue concept the SMS side has no equivalent of."""
import os
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin import require_admin_recent_2fa, require_staff
from .database import get_db
from .models import BankTransferTopupRequest, Entity, Organization, TextziWallet, User
from .schemas import (
    BankTransferTopupRequestAdminOut, BankTransferTopupRequestReview, TextziWalletAdminAdjustmentResponse,
    TextziWalletAdminCreditRequest, TextziWalletAdminDebitRequest,
)
from .security import decode_access_token
from .services import DomainError, credit_textzi_wallet_manual, debit_textzi_wallet, log_activity

router = APIRouter(prefix="/v1/admin/textzi-wallet", tags=["admin"])


def _resolve_caller(db: Session, authorization: str | None) -> User | None:
    """Same manual bearer-token decode admin.py's own debit_wallet_admin/update_profile_change_request
    already use -- require_admin/require_staff accept an X-Admin-Key bootstrap path with no
    associated User at all, so a real User can't come from a Depends() the way it would for an
    ordinary authenticated endpoint; this is the established way to attribute an admin action to
    a specific person when one is actually logged in, falling back to None for the bootstrap key."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
        return db.get(User, claims.get("sub"))
    except jwt.PyJWTError:
        return None


def _request_admin_out(db: Session, row: BankTransferTopupRequest) -> BankTransferTopupRequestAdminOut:
    entity = db.get(Entity, row.entity_id)
    org = db.get(Organization, entity.organization_id) if entity else None
    return BankTransferTopupRequestAdminOut(
        id=row.id, entity_id=row.entity_id, organization_name=org.name if org else None,
        transfer_date=row.transfer_date.date().isoformat(), mode=row.mode, amount=float(row.amount),
        utr_number=row.utr_number, notes=row.notes, status=row.status,
        credited_amount=float(row.credited_amount) if row.credited_amount is not None else None,
        admin_note=row.admin_note, reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        created_at=row.created_at.isoformat(),
    )


@router.get("/requests", response_model=list[BankTransferTopupRequestAdminOut], dependencies=[Depends(require_staff("finance")), Depends(require_admin_recent_2fa)])
def list_bank_transfer_requests(request_status: str | None = None, db: Session = Depends(get_db)):
    query = select(BankTransferTopupRequest).order_by(BankTransferTopupRequest.created_at.desc())
    if request_status:
        query = query.where(BankTransferTopupRequest.status == request_status)
    rows = db.scalars(query).all()
    return [_request_admin_out(db, row) for row in rows]


@router.get("/requests/{request_id}/receipt", dependencies=[Depends(require_staff("finance")), Depends(require_admin_recent_2fa)])
def download_bank_transfer_receipt(request_id: str, db: Session = Depends(get_db)):
    row = db.get(BankTransferTopupRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    ext = os.path.splitext(row.receipt_path)[1]
    media_type = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext.lower())
    # No `filename=` -- that forces Content-Disposition: attachment (a download), but the admin
    # review UI's "View" link expects an inline preview, matching every other document-preview
    # endpoint in this codebase (e.g. the DLT document viewer).
    return FileResponse(row.receipt_path, media_type=media_type)


@router.patch("/requests/{request_id}", response_model=BankTransferTopupRequestAdminOut, dependencies=[Depends(require_staff("finance")), Depends(require_admin_recent_2fa)])
def review_bank_transfer_request(request_id: str, payload: BankTransferTopupRequestReview, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Approving requires the admin to enter credited_amount -- the amount actually verified
    against the real bank statement, not necessarily the customer's own claimed `amount` (see
    BankTransferTopupRequest's own docstring for why these are deliberately separate fields)."""
    row = db.get(BankTransferTopupRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    if row.status != "pending":
        raise HTTPException(status_code=422, detail="This request has already been reviewed")
    admin_user = _resolve_caller(db, authorization)

    if payload.status == "approved":
        if not payload.credited_amount:
            raise HTTPException(status_code=422, detail="credited_amount is required to approve a request")
        try:
            credit_textzi_wallet_manual(db, row.entity_id, payload.credited_amount, reference=f"bank_transfer:{row.id}", admin_user=admin_user)
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        row.credited_amount = payload.credited_amount

    row.status = payload.status
    row.admin_note = payload.admin_note
    row.reviewed_by = admin_user.id if admin_user else None
    row.reviewed_at = datetime.now(timezone.utc)
    log_activity(
        db, None, "bank_transfer_request_reviewed",
        f"Bank transfer request {row.id} for entity {row.entity_id} {payload.status}" + (f" (credited Rs.{payload.credited_amount})" if payload.status == "approved" else ""),
        user_id=admin_user.id if admin_user else None, actor_email=admin_user.email if admin_user else "admin (bootstrap key)", request=request,
    )
    db.commit()
    db.refresh(row)
    return _request_admin_out(db, row)


@router.post("/credit", response_model=TextziWalletAdminAdjustmentResponse, dependencies=[Depends(require_staff("finance")), Depends(require_admin_recent_2fa)])
def admin_credit_textzi_wallet(payload: TextziWalletAdminCreditRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    entity = db.get(Entity, payload.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    admin_user = _resolve_caller(db, authorization)
    wallet = credit_textzi_wallet_manual(db, entity.id, payload.amount, reference=payload.notes or "Admin manual credit", admin_user=admin_user)
    db.commit()
    return TextziWalletAdminAdjustmentResponse(entity_id=entity.id, amount=payload.amount, balance=float(wallet.balance))


@router.post("/debit", response_model=TextziWalletAdminAdjustmentResponse, dependencies=[Depends(require_staff("finance")), Depends(require_admin_recent_2fa)])
def admin_debit_textzi_wallet(payload: TextziWalletAdminDebitRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    entity = db.get(Entity, payload.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    admin_user = _resolve_caller(db, authorization)
    try:
        wallet = debit_textzi_wallet(db, entity.id, payload.amount, transaction_type="admin_manual_debit", reference=payload.notes or "Admin manual debit")
    except DomainError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(
        db, entity.organization_id, "textzi_wallet_manual_debit",
        f"Textzi Wallet manually debited Rs.{payload.amount} for entity {entity.id}",
        user_id=admin_user.id if admin_user else None, actor_email=admin_user.email if admin_user else "admin (bootstrap key)", request=request,
    )
    db.commit()
    return TextziWalletAdminAdjustmentResponse(entity_id=entity.id, amount=payload.amount, balance=float(wallet.balance))


@router.get("/entities/{entity_id}/balance", response_model=TextziWalletAdminAdjustmentResponse, dependencies=[Depends(require_staff("finance")), Depends(require_admin_recent_2fa)])
def get_entity_textzi_wallet_balance(entity_id: str, db: Session = Depends(get_db)):
    wallet = db.get(TextziWallet, entity_id)
    return TextziWalletAdminAdjustmentResponse(entity_id=entity_id, amount=0, balance=float(wallet.balance) if wallet else 0.0)
