"""TOTP enrollment for one's own account. Login-time verification (`/v1/auth/login/verify-2fa`)
and step-up re-verification (`/v1/auth/step-up-2fa`) live in auth.py alongside `require_user`,
since both need direct access to token issuance; this router only manages the secret itself."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .auth import _verify_totp_with_lockout, require_user
from .database import get_db
from .models import TwoFactorAuth, User
from .schemas import TwoFactorCodeRequest, TwoFactorEnrollResponse, TwoFactorStatusOut
from .security import encrypt_secret, generate_totp_secret, totp_uri
from .services import log_activity

router = APIRouter(prefix="/v1/auth/2fa", tags=["2fa"])


@router.get("/status", response_model=TwoFactorStatusOut)
def get_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(TwoFactorAuth, user.id)
    return TwoFactorStatusOut(enabled=bool(row and row.enabled))


@router.post("/enroll", response_model=TwoFactorEnrollResponse)
def enroll(user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(TwoFactorAuth, user.id)
    if row and row.enabled:
        raise HTTPException(status_code=422, detail="2FA is already enabled; disable it first to re-enroll")
    secret = generate_totp_secret()
    if row:
        row.secret_encrypted = encrypt_secret(secret)
    else:
        row = TwoFactorAuth(user_id=user.id, secret_encrypted=encrypt_secret(secret))
        db.add(row)
    db.commit()
    return TwoFactorEnrollResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/confirm", response_model=TwoFactorStatusOut)
def confirm(payload: TwoFactorCodeRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(TwoFactorAuth, user.id)
    if not row:
        raise HTTPException(status_code=422, detail="Start enrollment first")
    if row.enabled:
        raise HTTPException(status_code=422, detail="2FA is already enabled")
    _verify_totp_with_lockout(db, row, payload.code)
    row.enabled = True
    row.enabled_at = datetime.now(timezone.utc)
    log_activity(db, user.organization_id, "2fa_enabled", "Two-factor authentication enabled.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return TwoFactorStatusOut(enabled=True)


@router.post("/disable", response_model=TwoFactorStatusOut)
def disable(payload: TwoFactorCodeRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(TwoFactorAuth, user.id)
    if not row or not row.enabled:
        raise HTTPException(status_code=422, detail="2FA is not enabled")
    _verify_totp_with_lockout(db, row, payload.code)
    db.delete(row)
    log_activity(db, user.organization_id, "2fa_disabled", "Two-factor authentication disabled.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return TwoFactorStatusOut(enabled=False)
