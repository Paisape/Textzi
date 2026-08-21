"""Customer-facing WhatsApp Business Account connection via Meta's Embedded Signup. This is
onboarding only (connect/disconnect a number) -- the actual send/receive dispatch pipeline is
separate, later work per the WABA plan. Deliberately its own module, never importing from or
importing into dispatch.py/providers.py/webhooks.py (the SMS-specific pipeline) -- the whole
point of the native rebuild is that a WABA bug can't touch SMS and vice versa."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import User, WabaConnection
from .schemas import (
    BusinessProfileOut, BusinessProfileUpdateRequest, CatalogIdUpdateRequest, RegisterPhoneRequest, WabaConfigOut, WabaConnectRequest, WabaDirectConnectRequest,
    WabaStatusOut, WabaStatusRefreshOut,
)
from .permissions import require_channel_scope
from .security import decrypt_secret, encrypt_secret, generate_otp
from .services import DomainError, channel_active, channel_enabled, get_platform_waba_settings, log_activity, resolve_user_entity
from .waba_dispatch import _log_api_call
from .waba_meta import (
    MetaApiError, exchange_code_for_token, fetch_business_profile, fetch_phone_number_details, fetch_phone_number_status,
    register_phone_number, subscribe_app_to_waba, update_business_profile,
)

router = APIRouter(prefix="/v1/waba", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])


@router.get("/config", response_model=WabaConfigOut)
def get_waba_config(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """app_id/config_id aren't secrets (app_id is embedded in the Facebook JS SDK on every
    customer's browser regardless) -- gated behind require_user anyway (unlike Turnstile's
    equivalent public endpoint) since there's no reason a logged-out visitor would ever need to
    launch embedded signup; this is only ever called from the already-authenticated channel
    settings page."""
    app_id, config_id, _ = get_platform_waba_settings(db)
    if not app_id or not config_id:
        raise HTTPException(status_code=422, detail="WhatsApp is not configured on this platform yet -- contact support.")
    return WabaConfigOut(app_id=app_id, config_id=config_id)


@router.get("/status", response_model=WabaStatusOut)
def get_waba_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not channel_active(db, entity.id, "waba"):
        return WabaStatusOut(connected=False)
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        return WabaStatusOut(connected=False)
    return WabaStatusOut(
        connected=True, phone_number=connection.phone_number, verified_name=connection.verified_name,
        waba_id=connection.waba_id, connected_at=connection.connected_at.isoformat(),
        quality_rating=connection.quality_rating, messaging_tier=connection.messaging_tier,
        status_checked_at=connection.status_checked_at.isoformat() if connection.status_checked_at else None,
        catalog_id=connection.catalog_id,
    )


@router.put("/catalog-id", response_model=WabaStatusOut)
def update_catalog_id(payload: CatalogIdUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Plain text field, not validated against Meta -- the catalog itself lives entirely in Meta
    Commerce Manager, created and populated by the customer there; this is just the reference
    product/catalog message sends need for `action.catalog_id`."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number first")
    connection.catalog_id = payload.catalog_id.strip() if payload.catalog_id else None
    db.commit()
    return get_waba_status(user, db)


@router.post("/connect", response_model=WabaStatusOut)
def connect_waba(payload: WabaConnectRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Exchanges the embedded-signup authorization code (30-second TTL per Meta's own docs --
    the frontend must call this immediately after receiving it) for a long-lived access token,
    subscribes Textzi's app to this WABA's webhooks, and stores the connection. waba_id/
    phone_number_id/business_id come from the frontend's own capture of Meta's postMessage
    WA_EMBEDDED_SIGNUP event -- Meta doesn't return these from the code-exchange call itself."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not channel_enabled(db, "waba"):
        raise HTTPException(status_code=422, detail="WhatsApp isn't available on this platform right now.")
    app_id, _, app_secret = get_platform_waba_settings(db)
    if not app_id or not app_secret:
        raise HTTPException(status_code=422, detail="WhatsApp is not configured on this platform yet -- contact support.")

    try:
        access_token = exchange_code_for_token(app_id, app_secret, payload.code)
        subscribe_app_to_waba(payload.waba_id, access_token)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not complete the WhatsApp connection: {exc}") from exc

    connection = db.get(WabaConnection, entity.id)
    # Meta ties a phone number to its two-step-verification PIN on first registration -- later
    # /register calls for the SAME number must reuse that SAME PIN, not a fresh one, or
    # registration fails. Reuse the stored PIN only if this is the same number as before;
    # otherwise (first-ever connection, or a different number this time) mint a fresh one.
    if connection and connection.phone_number_id == payload.phone_number_id and connection.registration_pin_encrypted:
        pin = decrypt_secret(connection.registration_pin_encrypted)
    else:
        pin = generate_otp()

    # Best-effort: confirmed live this session that this genuinely is required (Meta error 133010
    # "Account not registered" on the first send otherwise) -- still doesn't roll back the
    # connection on failure, since the webhook subscription above is the part that matters most
    # for Textzi to function, and POST /register-phone below lets the customer retry this specific
    # step on its own once whatever caused it to fail is fixed. The PIN is persisted below
    # regardless of outcome, so a later retry (this same code path, or /register-phone) reuses it.
    try:
        register_phone_number(payload.phone_number_id, access_token, pin)
        _log_api_call(db, entity.id, "register", "ok", "registered", payload.phone_number_id)
    except MetaApiError as exc:
        _log_api_call(db, entity.id, "register", "error", str(exc), payload.phone_number_id)

    phone_number, verified_name = None, None
    try:
        details = fetch_phone_number_details(payload.phone_number_id, access_token)
        phone_number, verified_name = details.get("display_phone_number"), details.get("verified_name")
    except MetaApiError:
        pass

    if not connection:
        connection = WabaConnection(entity_id=entity.id)
        db.add(connection)
    connection.waba_id = payload.waba_id
    connection.phone_number_id = payload.phone_number_id
    connection.business_id = payload.business_id
    connection.phone_number = phone_number
    connection.verified_name = verified_name
    connection.access_token_encrypted = encrypt_secret(access_token)
    connection.registration_pin_encrypted = encrypt_secret(pin)
    connection.status = "connected"
    connection.connected_at = datetime.now(timezone.utc)
    connection.disconnected_at = None
    log_activity(db, user.organization_id, "waba_connected", f"WhatsApp Business Account connected (waba_id={payload.waba_id}).", user_id=user.id, actor_email=user.email, request=request)
    try:
        db.commit()
    except IntegrityError:
        # WabaConnection.entity_id is the PK -- a concurrent connect attempt for this same
        # never-before-connected entity can insert first. The Meta-side calls above already
        # happened either way; report a clean 409 instead of a raw 500.
        db.rollback()
        raise HTTPException(status_code=409, detail="This WhatsApp number was just connected by another request. Refresh and try again.") from None
    db.refresh(connection)
    return WabaStatusOut(
        connected=True, phone_number=connection.phone_number, verified_name=connection.verified_name,
        waba_id=connection.waba_id, connected_at=connection.connected_at.isoformat(),
    )


@router.post("/connect-direct", response_model=WabaStatusOut)
def connect_waba_direct(payload: WabaDirectConnectRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Manual fallback for when Embedded Signup isn't configured yet (no Configuration ID saved
    in platform settings) -- same end state as connect_waba, just skipping the authorization-code
    exchange since the caller already has a real access token in hand. Meta's WhatsApp > API
    Setup page hands out a temporary (24h) token plus the waba_id/phone_number_id for free,
    no App Review needed, which is enough to test with or record the App Review demo videos; a
    permanent System User token (Business Settings > System Users) works the same way for
    ongoing use."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not channel_enabled(db, "waba"):
        raise HTTPException(status_code=422, detail="WhatsApp isn't available on this platform right now.")

    try:
        subscribe_app_to_waba(payload.waba_id, payload.access_token)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not complete the WhatsApp connection: {exc}") from exc

    connection = db.get(WabaConnection, entity.id)
    if connection and connection.phone_number_id == payload.phone_number_id and connection.registration_pin_encrypted:
        pin = decrypt_secret(connection.registration_pin_encrypted)
    else:
        pin = generate_otp()
    try:
        register_phone_number(payload.phone_number_id, payload.access_token, pin)
        _log_api_call(db, entity.id, "register", "ok", "registered", payload.phone_number_id)
    except MetaApiError as exc:
        _log_api_call(db, entity.id, "register", "error", str(exc), payload.phone_number_id)

    phone_number, verified_name = None, None
    try:
        details = fetch_phone_number_details(payload.phone_number_id, payload.access_token)
        phone_number, verified_name = details.get("display_phone_number"), details.get("verified_name")
    except MetaApiError:
        pass

    if not connection:
        connection = WabaConnection(entity_id=entity.id)
        db.add(connection)
    connection.waba_id = payload.waba_id
    connection.phone_number_id = payload.phone_number_id
    connection.business_id = payload.business_id
    connection.phone_number = phone_number
    connection.verified_name = verified_name
    connection.access_token_encrypted = encrypt_secret(payload.access_token)
    connection.registration_pin_encrypted = encrypt_secret(pin)
    connection.status = "connected"
    connection.connected_at = datetime.now(timezone.utc)
    connection.disconnected_at = None
    log_activity(db, user.organization_id, "waba_connected", f"WhatsApp Business Account connected directly (waba_id={payload.waba_id}).", user_id=user.id, actor_email=user.email, request=request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This WhatsApp number was just connected by another request. Refresh and try again.") from None
    db.refresh(connection)
    return WabaStatusOut(
        connected=True, phone_number=connection.phone_number, verified_name=connection.verified_name,
        waba_id=connection.waba_id, connected_at=connection.connected_at.isoformat(),
    )


@router.post("/disconnect", response_model=WabaStatusOut)
def disconnect_waba(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Soft-disconnect -- keeps the row (audit trail, matches this codebase's convention
    elsewhere of not hard-deleting connection/billing-relevant history) but clears the access
    token immediately so it can't be used even if the row were somehow read again."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="No connected WhatsApp number to disconnect")
    connection.status = "disconnected"
    connection.access_token_encrypted = ""
    connection.disconnected_at = datetime.now(timezone.utc)
    log_activity(db, user.organization_id, "waba_disconnected", f"WhatsApp Business Account disconnected (waba_id={connection.waba_id}).", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return WabaStatusOut(connected=False)


def _connected_waba(db: Session, entity_id: str) -> WabaConnection:
    connection = db.get(WabaConnection, entity_id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number first")
    return connection


@router.post("/register-phone")
def register_connected_phone(payload: RegisterPhoneRequest = RegisterPhoneRequest(), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Manual retry for phone-number registration -- connect_waba/connect_waba_direct already
    attempt this automatically (best-effort, so a failure there doesn't undo an otherwise-working
    connection), but that failure was previously silent. This surfaces the real Meta error (e.g.
    133010 "Account not registered", or 400 "Invalid parameter" when payload.pin doesn't match a
    two-step verification PIN the number already had set on Meta's side before connecting here)
    back to the customer so they can act on it directly instead of only finding out the first time
    an actual message send fails."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = _connected_waba(db, entity.id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    if payload.pin:
        pin = payload.pin
    elif connection.registration_pin_encrypted:
        pin = decrypt_secret(connection.registration_pin_encrypted)
    else:
        pin = generate_otp()
    try:
        register_phone_number(connection.phone_number_id, access_token, pin)
    except MetaApiError as exc:
        _log_api_call(db, entity.id, "register", "error", str(exc), connection.phone_number_id)
        raise HTTPException(status_code=422, detail=f"Meta rejected the registration: {exc}") from exc
    _log_api_call(db, entity.id, "register", "ok", "registered", connection.phone_number_id)
    connection.registration_pin_encrypted = encrypt_secret(pin)
    db.commit()
    return {"registered": True}


@router.post("/refresh-status", response_model=WabaStatusRefreshOut)
def refresh_waba_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Pulls quality_rating and throughput (messaging tier) live from Meta -- deliberately not
    fetched on every /status call (that's read constantly, e.g. every inbox page load); this is
    only spent when an admin/agent explicitly asks to see current standing."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = _connected_waba(db, entity.id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        status = fetch_phone_number_status(connection.phone_number_id, access_token)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not fetch status from Meta: {exc}") from exc
    connection.quality_rating = status.get("quality_rating")
    throughput = status.get("throughput") or {}
    connection.messaging_tier = throughput.get("level")
    connection.status_checked_at = datetime.now(timezone.utc)
    db.commit()
    return WabaStatusRefreshOut(
        quality_rating=connection.quality_rating, messaging_tier=connection.messaging_tier,
        status_checked_at=connection.status_checked_at.isoformat(),
    )


@router.get("/business-profile", response_model=BusinessProfileOut)
def get_business_profile(user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = _connected_waba(db, entity.id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        profile = fetch_business_profile(connection.phone_number_id, access_token)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not load business profile from Meta: {exc}") from exc
    return BusinessProfileOut(
        about=profile.get("about"), address=profile.get("address"), description=profile.get("description"),
        email=profile.get("email"), profile_picture_url=profile.get("profile_picture_url"),
        websites=profile.get("websites", []), vertical=profile.get("vertical"),
    )


@router.put("/business-profile", response_model=BusinessProfileOut)
def update_waba_business_profile(payload: BusinessProfileUpdateRequest, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = _connected_waba(db, entity.id)
    access_token = decrypt_secret(connection.access_token_encrypted)
    # Only fields the caller actually set go to Meta -- update_business_profile leaves everything
    # else untouched on Meta's side, so this must not send a bunch of nulls for fields the agent
    # simply didn't edit this time.
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    try:
        update_business_profile(connection.phone_number_id, access_token, updates)
        profile = fetch_business_profile(connection.phone_number_id, access_token)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=f"Could not update business profile: {exc}") from exc
    log_activity(db, user.organization_id, "waba_business_profile_updated", "WhatsApp business profile updated.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    return BusinessProfileOut(
        about=profile.get("about"), address=profile.get("address"), description=profile.get("description"),
        email=profile.get("email"), profile_picture_url=profile.get("profile_picture_url"),
        websites=profile.get("websites", []), vertical=profile.get("vertical"),
    )
