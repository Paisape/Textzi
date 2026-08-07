"""Admin-only configuration for the platform's own operational sending -- its SMS sender
identity, its SMTP config, and its wallet. Deliberately separate from every tenant-facing router:
this is Textzi's own infrastructure, not something any customer sees or touches."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin import _caller_email, require_admin, require_admin_recent_2fa
from .auth import send_platform_test_sms
from .database import get_db
from .models import PlatformGeneralSettings, PlatformR2Settings, PlatformSmsSettings, PlatformSmtpSettings, PlatformWallet, PlatformWalletTransaction, PlatformZohoSettings
from .schemas import (
    PlatformGeneralSettingsOut, PlatformGeneralSettingsUpdate,
    PlatformR2SettingsOut, PlatformR2SettingsUpdate, PlatformSmsSettingsOut, PlatformSmsSettingsUpdate, PlatformSmtpSettingsOut, PlatformSmtpSettingsUpdate,
    PlatformTestSmsRequest, PlatformTestSmsResponse, PlatformWalletOut, PlatformWalletTopupRequest, PlatformWalletTransactionOut,
    PlatformZohoSettingsOut, PlatformZohoSettingsUpdate, ZohoAccountOut, ZohoConnectRequest, ZohoTaxRateOut,
)
from .security import encrypt_secret
from .services import DomainError, credit_platform_wallet, get_platform_company_info, log_activity, mask_mobile
from .zoho_books import ZohoCallError, exchange_grant_code, get_zoho_settings, list_accounts, list_tax_rates

router = APIRouter(prefix="/v1/admin/platform", tags=["platform-admin"])


@router.get("/sms-settings", response_model=PlatformSmsSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_sms_settings(db: Session = Depends(get_db)):
    row = db.get(PlatformSmsSettings, "platform")
    if not row:
        row = PlatformSmsSettings(id="platform")
    return PlatformSmsSettingsOut(pe_id=row.pe_id, pe_operator=row.pe_operator, header_id=row.header_id, sender_id=row.sender_id, dlt_template_id=row.dlt_template_id, template_body=row.template_body, route=row.route)


@router.put("/sms-settings", response_model=PlatformSmsSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_sms_settings(payload: PlatformSmsSettingsUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    row = db.get(PlatformSmsSettings, "platform")
    if not row:
        row = PlatformSmsSettings(id="platform")
        db.add(row)
    row.pe_id = payload.pe_id
    row.pe_operator = payload.pe_operator
    row.header_id = payload.header_id
    row.sender_id = payload.sender_id
    row.dlt_template_id = payload.dlt_template_id
    row.template_body = payload.template_body
    row.route = payload.route
    log_activity(db, None, "platform_sms_settings_updated", "Platform SMS settings updated.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(row)
    return PlatformSmsSettingsOut(pe_id=row.pe_id, pe_operator=row.pe_operator, header_id=row.header_id, sender_id=row.sender_id, dlt_template_id=row.dlt_template_id, template_body=row.template_body, route=row.route)


@router.get("/smtp-settings", response_model=PlatformSmtpSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_smtp_settings(db: Session = Depends(get_db)):
    row = db.get(PlatformSmtpSettings, "platform")
    if not row:
        row = PlatformSmtpSettings(id="platform", port=587, from_address="no-reply@textzi.in", use_tls=True)
    return PlatformSmtpSettingsOut(host=row.host, port=row.port, username=row.username, from_address=row.from_address, use_tls=row.use_tls, configured=bool(row.host))


@router.put("/smtp-settings", response_model=PlatformSmtpSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_smtp_settings(payload: PlatformSmtpSettingsUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    row = db.get(PlatformSmtpSettings, "platform")
    if not row:
        row = PlatformSmtpSettings(id="platform")
        db.add(row)
    row.host = payload.host
    row.port = payload.port
    row.username = payload.username
    if payload.password:
        row.password_encrypted = encrypt_secret(payload.password)
    row.from_address = payload.from_address
    row.use_tls = payload.use_tls
    log_activity(db, None, "platform_smtp_settings_updated", "Platform SMTP settings updated.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(row)
    return PlatformSmtpSettingsOut(host=row.host, port=row.port, username=row.username, from_address=row.from_address, use_tls=row.use_tls, configured=bool(row.host))


@router.get("/r2-settings", response_model=PlatformR2SettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_r2_settings(db: Session = Depends(get_db)):
    row = db.get(PlatformR2Settings, "platform")
    if not row:
        row = PlatformR2Settings(id="platform")
    return PlatformR2SettingsOut(
        account_id=row.account_id, access_key_id=row.access_key_id, bucket_name=row.bucket_name,
        configured=bool(row.account_id and row.access_key_id and row.secret_access_key_encrypted and row.bucket_name),
    )


@router.put("/r2-settings", response_model=PlatformR2SettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_r2_settings(payload: PlatformR2SettingsUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """secret_access_key is write-only, same convention as the SMTP password and Zoho client_secret
    -- GET never returns it, and a blank value on PUT keeps whatever was already stored."""
    row = db.get(PlatformR2Settings, "platform")
    if not row:
        row = PlatformR2Settings(id="platform")
        db.add(row)
    row.account_id = payload.account_id
    row.access_key_id = payload.access_key_id
    if payload.secret_access_key:
        row.secret_access_key_encrypted = encrypt_secret(payload.secret_access_key)
    row.bucket_name = payload.bucket_name
    log_activity(db, None, "platform_r2_settings_updated", "Platform R2 archive storage settings updated.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(row)
    return PlatformR2SettingsOut(
        account_id=row.account_id, access_key_id=row.access_key_id, bucket_name=row.bucket_name,
        configured=bool(row.account_id and row.access_key_id and row.secret_access_key_encrypted and row.bucket_name),
    )


@router.get("/zoho-settings", response_model=PlatformZohoSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_zoho_settings_admin(db: Session = Depends(get_db)):
    row = db.get(PlatformZohoSettings, "platform")
    if not row:
        row = PlatformZohoSettings(id="platform")
    return PlatformZohoSettingsOut(
        client_id=row.client_id, accounts_domain=row.accounts_domain, api_domain=row.api_domain, organization_id=row.organization_id,
        gst_tax_id_intrastate=row.gst_tax_id_intrastate, gst_tax_id_interstate=row.gst_tax_id_interstate, gst_tax_id_zero_rated=row.gst_tax_id_zero_rated,
        payment_deposit_account_id=row.payment_deposit_account_id,
        item_code_sms_service=row.item_code_sms_service, item_code_platform_fee_dlt=row.item_code_platform_fee_dlt,
        item_code_platform_fee_whatsapp=row.item_code_platform_fee_whatsapp,
        configured=bool(row.client_id and row.client_secret_encrypted and row.accounts_domain),
        connected=bool(row.refresh_token_encrypted and row.api_domain and row.organization_id),
    )


@router.put("/zoho-settings", response_model=PlatformZohoSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_zoho_settings(payload: PlatformZohoSettingsUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """client_secret is write-only, same convention as the SMTP password -- GET never returns it,
    and a blank value on PUT keeps whatever was already stored. Changing client_id/client_secret/
    accounts_domain after a Connect has already happened does NOT itself invalidate the stored
    refresh token -- it's tied to whichever client/DC it was actually issued against -- so a
    genuine credential change needs a fresh Connect (POST .../zoho-connect) afterward."""
    row = db.get(PlatformZohoSettings, "platform")
    if not row:
        row = PlatformZohoSettings(id="platform")
        db.add(row)
    row.client_id = payload.client_id
    if payload.client_secret:
        row.client_secret_encrypted = encrypt_secret(payload.client_secret)
    row.accounts_domain = payload.accounts_domain
    row.organization_id = payload.organization_id
    row.gst_tax_id_intrastate = payload.gst_tax_id_intrastate
    row.gst_tax_id_interstate = payload.gst_tax_id_interstate
    row.gst_tax_id_zero_rated = payload.gst_tax_id_zero_rated
    row.payment_deposit_account_id = payload.payment_deposit_account_id
    row.item_code_sms_service = payload.item_code_sms_service
    row.item_code_platform_fee_dlt = payload.item_code_platform_fee_dlt
    row.item_code_platform_fee_whatsapp = payload.item_code_platform_fee_whatsapp
    log_activity(db, None, "platform_zoho_settings_updated", "Platform Zoho Books settings updated.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(row)
    return PlatformZohoSettingsOut(
        client_id=row.client_id, accounts_domain=row.accounts_domain, api_domain=row.api_domain, organization_id=row.organization_id,
        gst_tax_id_intrastate=row.gst_tax_id_intrastate, gst_tax_id_interstate=row.gst_tax_id_interstate, gst_tax_id_zero_rated=row.gst_tax_id_zero_rated,
        payment_deposit_account_id=row.payment_deposit_account_id,
        item_code_sms_service=row.item_code_sms_service, item_code_platform_fee_dlt=row.item_code_platform_fee_dlt,
        item_code_platform_fee_whatsapp=row.item_code_platform_fee_whatsapp,
        configured=bool(row.client_id and row.client_secret_encrypted and row.accounts_domain),
        connected=bool(row.refresh_token_encrypted and row.api_domain and row.organization_id),
    )


@router.post("/zoho-connect", response_model=PlatformZohoSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def connect_zoho(payload: ZohoConnectRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The one-time step after generating a grant/authorization code from api-console.zoho.com --
    exchanges it for a permanent refresh token. Only needs doing once per Zoho org connection;
    the resulting token is then refreshed automatically forever by zoho_books._access_token."""
    try:
        row = exchange_grant_code(db, payload.grant_code)
    except ZohoCallError as exc:
        raise HTTPException(status_code=502, detail=f"Could not connect to Zoho Books: {exc}") from exc
    log_activity(db, None, "platform_zoho_connected", "Platform Zoho Books connection established.", actor_email=_caller_email(authorization, db), request=request)
    return PlatformZohoSettingsOut(
        client_id=row.client_id, accounts_domain=row.accounts_domain, api_domain=row.api_domain, organization_id=row.organization_id,
        gst_tax_id_intrastate=row.gst_tax_id_intrastate, gst_tax_id_interstate=row.gst_tax_id_interstate, gst_tax_id_zero_rated=row.gst_tax_id_zero_rated,
        payment_deposit_account_id=row.payment_deposit_account_id,
        item_code_sms_service=row.item_code_sms_service, item_code_platform_fee_dlt=row.item_code_platform_fee_dlt,
        item_code_platform_fee_whatsapp=row.item_code_platform_fee_whatsapp,
        configured=bool(row.client_id and row.client_secret_encrypted and row.accounts_domain),
        connected=bool(row.refresh_token_encrypted and row.api_domain and row.organization_id),
    )


@router.get("/zoho-accounts", response_model=list[ZohoAccountOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_zoho_accounts(db: Session = Depends(get_db)):
    """Real Bank/Cash accounts from the connected Zoho org's chart of accounts, for the payment
    deposit account dropdown -- fetched live rather than free-typed, since these are opaque Zoho
    account_id GUIDs, not names."""
    settings_row = get_zoho_settings(db)
    if not settings_row:
        raise HTTPException(status_code=422, detail="Configure and connect Zoho Books first.")
    try:
        accounts = list_accounts(db, settings_row)
    except ZohoCallError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch accounts from Zoho Books: {exc}") from exc
    return [ZohoAccountOut(account_id=a["account_id"], account_name=a["account_name"], account_type=a.get("account_type") or "") for a in accounts]


@router.get("/zoho-tax-rates", response_model=list[ZohoTaxRateOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_zoho_tax_rates_admin(db: Session = Depends(get_db)):
    """Real configured tax rates from the connected Zoho org, for the intrastate (CGST+SGST) and
    interstate (IGST) tax rate dropdowns -- referencing one by tax_id is all Textzi needs to send;
    Zoho computes and posts the correct GST lines from the rate's own setup."""
    settings_row = get_zoho_settings(db)
    if not settings_row:
        raise HTTPException(status_code=422, detail="Configure and connect Zoho Books first.")
    try:
        rates = list_tax_rates(db, settings_row)
    except ZohoCallError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch tax rates from Zoho Books: {exc}") from exc
    return [ZohoTaxRateOut(tax_id=t["tax_id"], tax_name=t.get("tax_name", ""), tax_percentage=t.get("tax_percentage")) for t in rates]


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@router.get("/general-settings", response_model=PlatformGeneralSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_general_settings(db: Session = Depends(get_db)):
    info = get_platform_company_info(db)
    return PlatformGeneralSettingsOut(
        company_name=info.company_name, company_address=info.company_address, company_gstin=info.company_gstin,
        company_state=info.company_state, company_state_code=info.company_state_code, company_phone=info.company_phone,
        support_email=info.support_email, public_api_base_url=info.public_api_base_url,
    )


@router.put("/general-settings", response_model=PlatformGeneralSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_general_settings(payload: PlatformGeneralSettingsUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Every field is optional and blank-clears back to the .env fallback in config.py (see
    get_platform_company_info) -- there's no "leave unchanged" sentinel here because none of
    these values are secrets, unlike the SMTP password."""
    row = db.get(PlatformGeneralSettings, "platform")
    if not row:
        row = PlatformGeneralSettings(id="platform")
        db.add(row)
    row.company_name = _norm(payload.company_name)
    row.company_address = _norm(payload.company_address)
    row.company_gstin = _norm(payload.company_gstin)
    row.company_state = _norm(payload.company_state)
    row.company_state_code = _norm(payload.company_state_code)
    row.company_phone = _norm(payload.company_phone)
    row.support_email = _norm(payload.support_email)
    row.public_api_base_url = _norm(payload.public_api_base_url)
    log_activity(db, None, "platform_general_settings_updated", "Platform general settings updated.", actor_email=_caller_email(authorization, db), request=request)
    db.commit()
    info = get_platform_company_info(db)
    return PlatformGeneralSettingsOut(
        company_name=info.company_name, company_address=info.company_address, company_gstin=info.company_gstin,
        company_state=info.company_state, company_state_code=info.company_state_code, company_phone=info.company_phone,
        support_email=info.support_email, public_api_base_url=info.public_api_base_url,
    )


@router.get("/wallet", response_model=PlatformWalletOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_wallet(db: Session = Depends(get_db)):
    wallet = db.get(PlatformWallet, "platform")
    balance = float(wallet.balance) if wallet else 0.0
    transactions = db.scalars(select(PlatformWalletTransaction).order_by(PlatformWalletTransaction.created_at.desc()).limit(50)).all()
    return PlatformWalletOut(
        balance=balance,
        transactions=[PlatformWalletTransactionOut(id=t.id, type=t.type, amount=float(t.amount), balance_after=float(t.balance_after), reference=t.reference, created_at=t.created_at.isoformat()) for t in transactions],
    )


@router.post("/wallet/topup", response_model=PlatformWalletOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def topup_wallet(payload: PlatformWalletTopupRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    credit_platform_wallet(db, payload.amount, type="admin_topup", reference=payload.notes)
    log_activity(db, None, "platform_wallet_topup", f"Platform wallet topped up by {payload.amount} credits.", actor_email=_caller_email(authorization, db), request=request)
    db.commit()
    return get_wallet(db)


@router.post("/test-sms", response_model=PlatformTestSmsResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def send_test_sms(payload: PlatformTestSmsRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Fires a real send through the exact platform SMS pipeline (same PE_ID/template/route/
    TTBS recipient-prefixing as a real login OTP) to any number an admin types in -- built to
    debug delivery issues without a full registration/login round trip. Logged to the audit
    trail since, unlike a real OTP, this is a deliberate admin action with a real cost."""
    try:
        message = send_platform_test_sms(db, payload.recipient)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, None, "platform_test_sms", f"Sent a test SMS to {mask_mobile(payload.recipient)} (route {message.route}).", actor_email=_caller_email(authorization, db), request=request)
    db.commit()
    return PlatformTestSmsResponse(message_id=message.id, status=message.status, recipient=mask_mobile(message.recipient))
