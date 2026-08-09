"""TOTP enrollment for one's own account. Login-time verification (`/v1/auth/login/verify-2fa`)
and step-up re-verification (`/v1/auth/step-up-2fa`) live in auth.py alongside `require_user`,
since both need direct access to token issuance; this router only manages the secret itself."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .auth import _verify_2fa_code, _verify_totp_with_lockout, require_user
from .database import get_db
from .models import TwoFactorAuth, TwoFactorRecoveryCode, User
from .schemas import TwoFactorCodeRequest, TwoFactorConfirmResponse, TwoFactorEnrollResponse, TwoFactorRecoveryCodesOut, TwoFactorStatusOut
from .security import encrypt_secret, generate_recovery_code, generate_totp_secret, hash_otp, normalize_recovery_code, totp_uri
from .services import log_activity

router = APIRouter(prefix="/v1/auth/2fa", tags=["2fa"])


def _issue_recovery_codes(db: Session, user_id: str) -> list[str]:
    """Generates a fresh batch of 10 single-use recovery codes, persisting only their hashes --
    the plaintext values returned here are the only time they're ever visible; the caller's
    response is the last chance to show them to the user."""
    codes = [generate_recovery_code() for _ in range(10)]
    for code in codes:
        db.add(TwoFactorRecoveryCode(user_id=user_id, code_hash=hash_otp(normalize_recovery_code(code))))
    return codes


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


@router.post("/confirm", response_model=TwoFactorConfirmResponse)
def confirm(payload: TwoFactorCodeRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(TwoFactorAuth, user.id)
    if not row:
        raise HTTPException(status_code=422, detail="Start enrollment first")
    if row.enabled:
        raise HTTPException(status_code=422, detail="2FA is already enabled")
    # Deliberately the plain TOTP check, not the combined recovery-code-or-TOTP one -- no recovery
    # codes exist for this user yet at this point (they're issued a few lines below, for the first
    # time), so there's nothing for a recovery code to match here regardless.
    _verify_totp_with_lockout(db, row, payload.code)
    row.enabled = True
    row.enabled_at = datetime.now(timezone.utc)
    codes = _issue_recovery_codes(db, user.id)
    log_activity(db, user.organization_id, "2fa_enabled", "Two-factor authentication enabled.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return TwoFactorConfirmResponse(enabled=True, recovery_codes=codes)


@router.post("/recovery-codes/regenerate", response_model=TwoFactorRecoveryCodesOut)
def regenerate_recovery_codes(payload: TwoFactorCodeRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Invalidates every existing recovery code and issues a fresh batch of 10 -- e.g. after the
    user has used a few and wants a full set again, or suspects an old saved copy was exposed.
    Deliberately requires a live TOTP code (not the combined recovery-code-or-TOTP check other
    2FA actions accept) -- minting a fresh batch using an old recovery code would let a single
    leaked code perpetually renew itself instead of being truly single-use."""
    row = db.get(TwoFactorAuth, user.id)
    if not row or not row.enabled:
        raise HTTPException(status_code=422, detail="2FA is not enabled")
    _verify_totp_with_lockout(db, row, payload.code)
    db.execute(delete(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == user.id))
    codes = _issue_recovery_codes(db, user.id)
    log_activity(db, user.organization_id, "2fa_recovery_codes_regenerated", "Two-factor recovery codes regenerated.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return TwoFactorRecoveryCodesOut(recovery_codes=codes)


@router.post("/disable", response_model=TwoFactorStatusOut)
def disable(payload: TwoFactorCodeRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(TwoFactorAuth, user.id)
    if not row or not row.enabled:
        raise HTTPException(status_code=422, detail="2FA is not enabled")
    # Accepts a recovery code here too -- a user who's lost their authenticator device but still
    # has a saved recovery code can turn 2FA off themselves rather than needing an admin.
    _verify_2fa_code(db, row, payload.code)
    db.execute(delete(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == user.id))
    db.delete(row)
    log_activity(db, user.organization_id, "2fa_disabled", "Two-factor authentication disabled.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return TwoFactorStatusOut(enabled=False)
