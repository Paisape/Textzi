"""Registration journey: register -> verify email -> verify mobile -> login.

No real email/SMS sender is wired up yet, so verification codes are logged and, in development
only, echoed back in the response so the flow is testable end-to-end without a provider. In any
non-development environment this must be replaced by an actual email/SMS send (the OTP hash is
still all that's persisted either way — codes are never stored in plaintext)."""
import hmac
import html
import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .dispatch import provider_for_route
from .email_service import render_email, send_email
from .models import EmailVerification, MobileVerification, PasswordReset, PLATFORM_INTERNAL_ROLES, PlatformMessage, TwoFactorAuth, User, UserSession, UserStatus, uid
from .providers import ProviderMessage
from .schemas import (
    ChangePasswordRequest, ForgotPasswordRequest, ForgotPasswordResponse, LoginRequest, PermissionsResponse, RegisterRequest, RegisterResponse,
    RequestMobileOtpRequest, RequestMobileOtpResponse, ResetPasswordRequest, SessionOut,
    RegistrationStatusResponse, TokenResponse, TwoFactorCodeRequest, UserProfile, Verify2faRequest, VerifyEmailRequest, VerifyMobileRequest,
)
from .security import create_access_token, decode_access_token, decrypt_secret, generate_otp, hash_otp, hash_password, verify_password, verify_totp
from .services import DomainError, RateLimitError, capabilities_for, client_ip, debit_platform_wallet, enforce_rate_limit, get_platform_sms_settings, log_activity, mask_mobile, redact_otp, redact_payload_values, render_template, sms_segment_credits

logger = logging.getLogger("textzi.auth")
router = APIRouter(prefix="/v1/auth", tags=["auth"])

# Verified against on every login attempt for a non-existent email, so a request for an unknown
# address costs the same Argon2 verify time as a real one -- otherwise response latency alone
# reveals which emails are registered accounts.
_DUMMY_PASSWORD_HASH = hash_password("no-such-user-constant-time-placeholder")


def _issue_otp(db: Session, model, user_id: str, channel: str, destination: str, **extra) -> str:
    code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.otp_ttl_minutes)
    db.add(model(user_id=user_id, code_hash=hash_otp(code), expires_at=expires_at, **extra))
    db.commit()
    logger.info("otp issued channel=%s destination=%s user_id=%s", channel, destination, user_id)  # never logs the code itself
    return code


def _consume_otp(db: Session, model, user_id: str, code: str):
    record = db.scalar(select(model).where(model.user_id == user_id, model.consumed_at.is_(None)).order_by(model.created_at.desc()))
    if not record:
        raise HTTPException(status_code=422, detail="No pending verification code; request a new one")
    if record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Verification code has expired; request a new one")
    if record.attempts >= settings.otp_max_attempts:
        raise HTTPException(status_code=429, detail="Too many attempts; request a new code")
    record.attempts += 1
    if not hmac.compare_digest(record.code_hash, hash_otp(code)):
        db.commit()
        raise HTTPException(status_code=422, detail="Incorrect verification code")
    record.consumed_at = datetime.now(timezone.utc)
    db.commit()
    return record


@router.get("/registration-status/{user_id}", response_model=RegistrationStatusResponse)
def registration_status(user_id: str, db: Session = Depends(get_db)):
    """Public and unauthenticated, same trust model as verify-email/verify-mobile/
    request-mobile-otp themselves (this runs before any session exists) -- safe because user_id
    is an unguessable UUID (this project's own established convention: UUIDs don't need
    validation against enumeration) and this only ever reveals three booleans/a status string
    for a caller who already holds one, never anything else about the account.

    Lets /verify-account jump straight to whichever step the account is actually on, instead of
    always starting at "verify email" regardless of backend state -- confirmed live this left an
    already-email-verified account with no way to reach the mobile step at all, since submitting
    any code there now correctly refuses (see verify_email's own fix) rather than silently
    letting a stale step 1 pretend to succeed."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return RegistrationStatusResponse(email_verified=user.email_verified, mobile_verified=user.mobile_verified, status=user.status.value)


REGISTER_RATE_LIMIT_MAX_REQUESTS = 5
REGISTER_RATE_LIMIT_WINDOW_SECONDS = 3600


@router.post("/register", response_model=RegisterResponse)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # Unauthenticated and, on its own, fires a real email on every call -- without a limit this
    # is an open primitive for repeatedly emailing an arbitrary (non-yet-verified) address,
    # confirmed as a real gap: request_mobile_otp already has an equivalent cooldown/cap for the
    # exact same reason, this endpoint never did.
    try:
        enforce_rate_limit(f"ratelimit:register:{client_ip(request)}", REGISTER_RATE_LIMIT_MAX_REQUESTS, REGISTER_RATE_LIMIT_WINDOW_SECONDS)
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    # Normalized (stripped + lowercased) both for the new-row storage and for the lookup below via
    # func.lower() -- without this, "user@x.com" and "User@x.com" were treated as different
    # accounts (duplicate signups) and a genuine user logging in with different casing than they
    # registered with got a spurious "incorrect password".
    email = payload.email.strip().lower()
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing:
        # A genuinely registered account (email verified, or already past onboarding) must still
        # block a repeat registration -- otherwise this becomes an account-takeover vector (an
        # attacker "registering" a real, active email just to get a fresh password set on it).
        # But an account that never got past its own email-verification step is just an abandoned
        # signup -- nothing to protect there, and permanently locking that email out because
        # someone closed the tab before checking their inbox is a real, avoidable dead end.
        if existing.email_verified or existing.organization_id:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        user = existing
        user.password_hash = hash_password(payload.password)
        user.full_name = payload.full_name
        # A previously-suspended abandoned signup must resume as pending_verification, not stay
        # suspended -- otherwise request_mobile_otp's own status check rejects it with a
        # misleading "already completed verification", a dead end for an account that was never
        # actually completed.
        user.status = UserStatus.pending_verification
        db.commit()
    else:
        user = User(email=email, password_hash=hash_password(payload.password), full_name=payload.full_name, status=UserStatus.pending_verification)
        db.add(user); db.commit(); db.refresh(user)
    code = _issue_otp(db, EmailVerification, user.id, channel="email", destination=user.email)
    send_email(
        db,
        to=user.email,
        subject="Verify your Textzi account",
        html_body=render_email(
            "Verify your email address",
            f"<p>Hi {html.escape(user.full_name)},</p><p>Use the code below to verify your email and continue setting up your Textzi account.</p>"
            f"<p style=\"margin:24px 0; text-align:center;\"><span style=\"display:inline-block; font-size:28px; font-weight:bold; letter-spacing:6px; color:#1a1a1a; background:#f4f4f5; padding:12px 24px; border-radius:6px;\">{code}</span></p>"
            f"<p>This code expires in {settings.otp_ttl_minutes} minutes. If you didn't request this, you can safely ignore this email.</p>",
        ),
    )
    return RegisterResponse(user_id=user.id, email=user.email, next_step="verify_email", dev_email_code=code if settings.environment == "development" else None)


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email_verified:
        # Was previously an unconditional early-return -- meaning ANY code (wrong, blank,
        # expired) "succeeded" and advanced the wizard once email_verified was already true,
        # since _consume_otp was never even reached. Matches verify_mobile's own stricter
        # pattern now: refuse outright rather than silently accept an unvalidated code.
        raise HTTPException(status_code=422, detail="This email is already verified")
    _consume_otp(db, EmailVerification, user.id, payload.code)
    user.email_verified = True
    db.commit()
    return {"status": "verified", "next_step": "verify_mobile"}


def _send_platform_otp_sms(db: Session, mobile: str, code: str) -> bool:
    """Real SMS delivery for mobile-verification OTPs, using the platform's own dedicated sender
    identity (Admin -> Platform Settings -> SMS Setting) and its own wallet -- entirely separate
    from tenant Organizations/Entities/Messages. If unconfigured, or the platform wallet is
    underfunded, this fails open (no-op) -- the OTP is still usable via the logged code /
    dev_mobile_code echo, exactly as before this feature existed. Returns whether the provider
    actually accepted the send -- callers with no fallback channel (mobile-number verification
    at registration) can ignore this; callers that need a guaranteed delivery channel (the API
    key action OTP in channels.py) use it to fall back to email when this comes back False."""
    settings_row = get_platform_sms_settings(db)
    if not settings_row:
        return False
    rendered_body = render_template(settings_row.template_body, {"code": code})
    if not debit_platform_wallet(db, sms_segment_credits(rendered_body), type="otp_sms", reference=mobile):
        return False
    route = settings_row.route or "default-simulated-route"
    provider = provider_for_route(db, route)
    result = provider.send(ProviderMessage(
        message_id=uid(), recipient=mobile, sender=settings_row.sender_id, body=rendered_body,
        pe_id=settings_row.pe_id, template_id=settings_row.dlt_template_id,
    ))
    # Same by-value scrub as dispatch.py's encrypted-channel case -- the literal OTP code and the
    # recipient's number sit inside whatever field name the provider adapter used, so replace them
    # by their known plaintext value rather than by key.
    request_payload = redact_payload_values(result.request_payload, {rendered_body: redact_otp(rendered_body), mobile: mask_mobile(mobile)})
    db.add(PlatformMessage(
        purpose="mobile_otp", recipient=mobile, rendered_body=rendered_body, status="submitted" if result.accepted else "failed",
        route=route, provider_message_id=result.provider_message_id,
        request_payload=request_payload, response_body=result.response_body,
    ))
    db.commit()
    return result.accepted


def send_platform_test_sms(db: Session, recipient: str) -> PlatformMessage:
    """Admin-triggered end-to-end test of the exact same platform SMS pipeline (PE_ID, template,
    route, TTBS recipient-prefixing) _send_platform_otp_sms uses for real login/verification
    OTPs -- built so a delivery issue (e.g. the missing "91" prefix bug) can be reproduced and
    checked against a real handset without a full registration/login round trip. Unlike
    _send_platform_otp_sms, this never fails open: a missing config, empty wallet, or provider
    rejection must surface as a real error to the admin who explicitly asked for this send, not
    be swallowed."""
    settings_row = get_platform_sms_settings(db)
    if not settings_row:
        raise DomainError("Platform SMS is not configured yet -- set it up under Platform Settings > SMS Setting first.")
    code = generate_otp()
    rendered_body = render_template(settings_row.template_body, {"code": code})
    if not debit_platform_wallet(db, sms_segment_credits(rendered_body), type="test_sms", reference=recipient):
        raise DomainError("Platform wallet balance is too low to send a test SMS -- top it up under Platform Settings.")
    route = settings_row.route or "default-simulated-route"
    provider = provider_for_route(db, route)
    result = provider.send(ProviderMessage(
        message_id=uid(), recipient=recipient, sender=settings_row.sender_id, body=rendered_body,
        pe_id=settings_row.pe_id, template_id=settings_row.dlt_template_id,
    ))
    request_payload = redact_payload_values(result.request_payload, {rendered_body: redact_otp(rendered_body), recipient: mask_mobile(recipient)})
    message = PlatformMessage(
        purpose="test", recipient=recipient, rendered_body=rendered_body, status="submitted" if result.accepted else "failed",
        route=route, provider_message_id=result.provider_message_id,
        request_payload=request_payload, response_body=result.response_body,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    if not result.accepted:
        raise DomainError(result.error or "The SMS provider rejected the send.")
    return message


OTP_ISSUE_COOLDOWN_SECONDS = 30
OTP_ISSUE_MAX_PER_HOUR = 5


@router.post("/request-mobile-otp", response_model=RequestMobileOtpResponse)
def request_mobile_otp(payload: RequestMobileOtpRequest, db: Session = Depends(get_db)):
    """This endpoint is intentionally unauthenticated (it runs before a session token exists, as
    part of register -> verify-email -> verify-mobile), and the mobile number is caller-supplied
    -- without a limit, it's an open SMS-bomb-any-number-you-like primitive that also drains the
    platform wallet per send. Rate-limited per account: a short cooldown between requests plus a
    hard cap per rolling hour."""
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != UserStatus.pending_verification:
        # This pair of endpoints is unauthenticated by necessity (there's no session yet during
        # onboarding), which means user_id alone must never be enough to act on an account once
        # it's past this one-time flow -- otherwise anyone who learns a user_id (any teammate via
        # the Team page, any admin) could silently overwrite and re-verify a stranger's mobile
        # number at will, indefinitely. Once an account is active, this door is closed for good.
        raise HTTPException(status_code=422, detail="This account has already completed verification")
    if not user.email_verified:
        raise HTTPException(status_code=422, detail="Verify your email before adding a mobile number")

    now = datetime.now(timezone.utc)
    last = db.scalar(select(MobileVerification).where(MobileVerification.user_id == user.id).order_by(MobileVerification.created_at.desc()))
    if last:
        remaining = OTP_ISSUE_COOLDOWN_SECONDS - (now - last.created_at).total_seconds()
        if remaining > 0:
            raise HTTPException(status_code=429, detail=f"Please wait {int(remaining) + 1} seconds before requesting another code.")
    recent_count = db.scalar(select(func.count()).select_from(MobileVerification).where(MobileVerification.user_id == user.id, MobileVerification.created_at > now - timedelta(hours=1))) or 0
    if recent_count >= OTP_ISSUE_MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many verification code requests; please try again later.")

    user.mobile, user.mobile_verified = payload.mobile, False
    db.commit()
    code = _issue_otp(db, MobileVerification, user.id, channel="sms", destination=payload.mobile, mobile=payload.mobile)
    _send_platform_otp_sms(db, payload.mobile, code)
    return RequestMobileOtpResponse(mobile=payload.mobile, next_step="verify_mobile", dev_mobile_code=code if settings.environment == "development" else None)


@router.post("/verify-mobile")
def verify_mobile(payload: VerifyMobileRequest, db: Session = Depends(get_db)):
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != UserStatus.pending_verification:
        # Defense in depth alongside the same check in request_mobile_otp -- this is also the
        # call that flips status to active, so it must independently refuse to run twice.
        raise HTTPException(status_code=422, detail="This account has already completed verification")
    if not user.mobile:
        raise HTTPException(status_code=422, detail="Request a mobile OTP first")
    _consume_otp(db, MobileVerification, user.id, payload.code)
    user.mobile_verified = True
    user.status = UserStatus.active
    db.commit()
    return {"status": "verified", "next_step": "login"}


MFA_TOKEN_TTL_MINUTES = 5
STEP_UP_WINDOW_MINUTES = 15
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
TOTP_MAX_ATTEMPTS = 5
TOTP_LOCKOUT_MINUTES = 15
PASSWORD_RESET_TTL_MINUTES = 30


def _create_session(db: Session, user_id: str, request: Request | None) -> str:
    """One row per real login (password login, 2FA-verified login, invite acceptance) -- its id
    becomes the token's `sid` claim, and require_user rejects any token whose session has since
    been revoked. step_up_2fa is the one token-issuing exception: it reuses the caller's existing
    sid rather than calling this, since it's re-proving an existing session, not starting a new
    one."""
    session = UserSession(
        user_id=user_id,
        ip_address=client_ip(request) if request else None,
        user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
    )
    db.add(session)
    db.flush()
    return session.id


def _verify_totp_with_lockout(db: Session, two_factor: TwoFactorAuth, code: str) -> None:
    """Shared by login/verify-2fa, step-up-2fa, and (imported into two_factor.py) enroll-confirm
    and disable -- a TOTP code is only 6 digits, so without this an mfa_token (valid for the
    full 5-minute TTL) or an already-authenticated session could be used for unlimited guesses.
    Raises on failure (wrong code or currently locked out); returns normally on success and
    resets the counter."""
    if two_factor.locked_until and two_factor.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=429, detail="Too many incorrect codes; try again later")
    if not verify_totp(decrypt_secret(two_factor.secret_encrypted), code):
        two_factor.failed_attempts += 1
        if two_factor.failed_attempts >= TOTP_MAX_ATTEMPTS:
            two_factor.locked_until = datetime.now(timezone.utc) + timedelta(minutes=TOTP_LOCKOUT_MINUTES)
        db.commit()
        raise HTTPException(status_code=422, detail="Incorrect authenticator code")
    two_factor.failed_attempts = 0
    two_factor.locked_until = None
    db.commit()


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.strip().lower()))
    if user and user.login_locked_until and user.login_locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=429, detail="Too many failed login attempts; try again later")
    password_ok = verify_password(payload.password, user.password_hash if user else _DUMMY_PASSWORD_HASH)
    if not user or not password_ok:
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= LOGIN_MAX_ATTEMPTS:
                user.login_locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
                log_activity(db, user.organization_id, "login_locked", "Account locked after repeated failed login attempts.", user_id=user.id, actor_email=user.email, ip_address=ip, request=request)
            else:
                log_activity(db, user.organization_id, "login_failed", "Failed login attempt (incorrect password).", user_id=user.id, actor_email=user.email, ip_address=ip, request=request)
            db.commit()
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    user.failed_login_attempts = 0
    user.login_locked_until = None
    two_factor = db.get(TwoFactorAuth, user.id)
    if user.status == UserStatus.suspended:
        db.commit()
        raise HTTPException(status_code=403, detail="This account has been suspended. Contact an administrator for help.")
    if user.status != UserStatus.active:
        db.commit()
        raise HTTPException(status_code=403, detail="Complete email and mobile verification before logging in")
    if two_factor and two_factor.enabled:
        mfa_token = create_access_token(subject=user.id, extra_claims={"purpose": "mfa"}, ttl_minutes=MFA_TOKEN_TTL_MINUTES)
        db.commit()
        return TokenResponse(mfa_required=True, mfa_token=mfa_token)
    sid = _create_session(db, user.id, request)
    log_activity(db, user.organization_id, "login_success", "Logged in.", user_id=user.id, actor_email=user.email, ip_address=ip, request=request)
    db.commit()
    return TokenResponse(access_token=create_access_token(subject=user.id, extra_claims={"sid": sid}), mfa_required=False)


@router.post("/login/verify-2fa", response_model=TokenResponse)
def login_verify_2fa(payload: Verify2faRequest, request: Request, db: Session = Depends(get_db)):
    try:
        claims = decode_access_token(payload.mfa_token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired login session; sign in again")
    if claims.get("purpose") != "mfa":
        raise HTTPException(status_code=401, detail="Invalid or expired login session; sign in again")
    user = db.get(User, claims.get("sub"))
    two_factor = db.get(TwoFactorAuth, claims.get("sub")) if user else None
    if not user or user.status != UserStatus.active or not two_factor or not two_factor.enabled:
        raise HTTPException(status_code=401, detail="Invalid or expired login session; sign in again")
    _verify_totp_with_lockout(db, two_factor, payload.code)
    now = datetime.now(timezone.utc)
    sid = _create_session(db, user.id, request)
    token = create_access_token(subject=user.id, extra_claims={"mfa_verified_at": int(now.timestamp()), "sid": sid})
    log_activity(db, user.organization_id, "login_success", "Logged in (2FA verified).", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return TokenResponse(access_token=token, mfa_required=False)


def require_user(authorization: str = Header(...), db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if claims.get("purpose") == "mfa":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, claims.get("sub"))
    if not user or user.status != UserStatus.active:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    sid = claims.get("sid")
    if sid:
        session = db.get(UserSession, sid)
        if not session or session.revoked_at:
            raise HTTPException(status_code=401, detail="This session has been signed out; please log in again")
    return user


def _decode_bearer_claims(authorization: str) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return decode_access_token(authorization.removeprefix("Bearer ").strip())
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_recent_2fa(user: User = Depends(require_user), authorization: str = Header(...), db: Session = Depends(get_db)) -> User:
    """No-op when the user hasn't enabled 2FA -- fully opt-in and backward compatible. When
    enabled, the current token must carry a `mfa_verified_at` claim from within the last
    STEP_UP_WINDOW_MINUTES *and* from at or after the current TwoFactorAuth.enabled_at --
    otherwise a token stepped-up against a since-disabled-and-re-enrolled secret would still
    pass here without ever proving possession of the new one. The frontend is expected to
    prompt for a fresh code and retry via POST /v1/auth/step-up-2fa. 403, not 401 -- the token
    itself is still valid (require_user above already accepted it), just not fresh enough for
    this specific action, and $api's global interceptor (api.ts) treats any 401 on an
    authenticated request as a dead session and force-logs-out before the frontend's own
    step-up-dialog handler ever gets to inspect the error body."""
    two_factor = db.get(TwoFactorAuth, user.id)
    if not two_factor or not two_factor.enabled:
        return user
    claims = _decode_bearer_claims(authorization)
    verified_at = claims.get("mfa_verified_at")
    enabled_at_ts = two_factor.enabled_at.timestamp() if two_factor.enabled_at else 0
    if not verified_at or verified_at < enabled_at_ts or datetime.now(timezone.utc).timestamp() - verified_at > STEP_UP_WINDOW_MINUTES * 60:
        raise HTTPException(status_code=403, detail="step_up_required")
    return user


@router.post("/step-up-2fa", response_model=TokenResponse)
def step_up_2fa(payload: TwoFactorCodeRequest, user: User = Depends(require_user), authorization: str = Header(...), db: Session = Depends(get_db)):
    two_factor = db.get(TwoFactorAuth, user.id)
    if not two_factor or not two_factor.enabled:
        raise HTTPException(status_code=422, detail="2FA is not enabled on this account")
    _verify_totp_with_lockout(db, two_factor, payload.code)
    now = datetime.now(timezone.utc)
    # Reuses the caller's own sid rather than _create_session -- this re-proves an existing
    # session's freshness, it doesn't start a new login, so it shouldn't spawn a new session row.
    current_sid = _decode_bearer_claims(authorization).get("sid")
    extra_claims = {"mfa_verified_at": int(now.timestamp())}
    if current_sid:
        extra_claims["sid"] = current_sid
    token = create_access_token(subject=user.id, extra_claims=extra_claims)
    return TokenResponse(access_token=token, mfa_required=False)


@router.get("/me", response_model=UserProfile)
def me(user: User = Depends(require_user)):
    return UserProfile(id=user.id, email=user.email, full_name=user.full_name, email_verified=user.email_verified, mobile_verified=user.mobile_verified, status=user.status, organization_id=user.organization_id, role=user.role)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Self-service reset -- deliberately customer-side only. A platform-staff account
    (PLATFORM_INTERNAL_ROLES) never gets a code from this endpoint, no matter what: a public,
    unauthenticated, email-enumerable reset path is exactly the kind of attack surface you don't
    want in front of your most privileged accounts. Staff passwords only ever get reset by
    another admin (POST /v1/admin/users/{id}/reset-password). The response is identical whether
    or not the email exists or belongs to staff, to avoid leaking account existence/tier."""
    generic = ForgotPasswordResponse(message="If an account with that email exists, we've sent a password reset code.")
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.strip().lower()))
    # A suspended account must stay locked out through this public, unauthenticated path -- an
    # admin suspended it for a reason (abuse, fraud, non-payment), and letting anyone silently set
    # a new password for it defeats the suspension entirely: the account activates on whatever
    # attacker-chosen password was set the moment an admin later resolves the original issue and
    # reactivates it, with no visible sign anything happened in between. Same identical response
    # either way, so this adds no new account-existence signal beyond what already exists here.
    if not user or user.role in PLATFORM_INTERNAL_ROLES or user.status == UserStatus.suspended:
        return generic
    code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES)
    db.add(PasswordReset(user_id=user.id, code_hash=hash_otp(code), expires_at=expires_at))
    db.commit()
    send_email(
        db,
        to=user.email,
        subject="Reset your Textzi password",
        html_body=render_email(
            "Reset your password",
            f"<p>Hi {html.escape(user.full_name)},</p><p>Use the code below to reset your Textzi password.</p>"
            f"<p style=\"margin:24px 0; text-align:center;\"><span style=\"display:inline-block; font-size:28px; font-weight:bold; letter-spacing:6px; color:#1a1a1a; background:#f4f4f5; padding:12px 24px; border-radius:6px;\">{code}</span></p>"
            f"<p>This code expires in {PASSWORD_RESET_TTL_MINUTES} minutes. If you didn't request this, you can safely ignore this email.</p>",
        ),
    )
    if settings.environment == "development":
        return ForgotPasswordResponse(message=generic.message, dev_code=code, dev_user_id=user.id)
    return generic


@router.post("/reset-password", response_model=TokenResponse)
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    user = db.get(User, payload.user_id)
    if not user or user.role in PLATFORM_INTERNAL_ROLES or user.status == UserStatus.suspended:
        # Defense in depth alongside the same check in forgot_password -- covers a code issued
        # before the account was suspended and only redeemed after.
        raise HTTPException(status_code=422, detail="Invalid or expired reset code")
    record = db.scalar(select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.consumed_at.is_(None)).order_by(PasswordReset.created_at.desc()))
    if not record:
        raise HTTPException(status_code=422, detail="Invalid or expired reset code")
    if record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="This reset code has expired; request a new one")
    if record.attempts >= settings.otp_max_attempts:
        raise HTTPException(status_code=429, detail="Too many attempts; request a new code")
    record.attempts += 1
    if not hmac.compare_digest(record.code_hash, hash_otp(payload.code)):
        db.commit()
        raise HTTPException(status_code=422, detail="Invalid or expired reset code")
    record.consumed_at = datetime.now(timezone.utc)
    user.password_hash = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.login_locked_until = None
    sid = _create_session(db, user.id, request)
    log_activity(db, user.organization_id, "password_reset", "Password reset via forgot-password.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return TokenResponse(access_token=create_access_token(subject=user.id, extra_claims={"sid": sid}), mfa_required=False)


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Available to every account, staff included -- unlike forgot-password, this requires
    already knowing the current password, so it doesn't carry the same public-attack-surface
    risk. This is the password-change path for platform staff."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=422, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    log_activity(db, user.organization_id, "password_changed", "Password changed.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return {"status": "changed"}


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(user: User = Depends(require_user), authorization: str = Header(...), db: Session = Depends(get_db)):
    current_sid = _decode_bearer_claims(authorization).get("sid")
    sessions = db.scalars(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).order_by(UserSession.created_at.desc()),
    ).all()
    return [SessionOut(id=s.id, ip_address=s.ip_address, user_agent=s.user_agent, created_at=s.created_at.isoformat(), is_current=(s.id == current_sid)) for s in sessions]


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    session = db.get(UserSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "revoked"}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(user: User = Depends(require_user), authorization: str = Header(...), db: Session = Depends(get_db)):
    current_sid = _decode_bearer_claims(authorization).get("sid")
    sessions = db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))).all()
    count = 0
    for s in sessions:
        if s.id != current_sid:
            s.revoked_at = datetime.now(timezone.utc)
            count += 1
    db.commit()
    return {"status": "revoked", "count": count}


@router.get("/permissions", response_model=PermissionsResponse)
def permissions(user: User = Depends(require_user)):
    caps = capabilities_for(user.role)
    return PermissionsResponse(capabilities=["*"] if "*" in caps else sorted(caps))
