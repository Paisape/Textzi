"""Admin-only configuration for the platform's own operational sending -- its SMS sender
identity, its SMTP config, and its wallet. Deliberately separate from every tenant-facing router:
this is Textzi's own infrastructure, not something any customer sees or touches."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin import _caller_email, require_admin, require_admin_recent_2fa
from .auth import send_platform_test_sms
from .database import get_db
from .erpnext import ErpNextCallError, get_erpnext_settings, list_accounts, list_tax_templates
from .models import PlatformErpNextSettings, PlatformGeneralSettings, PlatformR2Settings, PlatformSmsSettings, PlatformSmtpSettings, PlatformWallet, PlatformWalletTransaction
from .schemas import (
    ErpNextAccountOut, ErpNextTaxTemplateOut, PlatformErpNextSettingsOut, PlatformErpNextSettingsUpdate, PlatformGeneralSettingsOut, PlatformGeneralSettingsUpdate,
    PlatformR2SettingsOut, PlatformR2SettingsUpdate, PlatformSmsSettingsOut, PlatformSmsSettingsUpdate, PlatformSmtpSettingsOut, PlatformSmtpSettingsUpdate,
    PlatformTestSmsRequest, PlatformTestSmsResponse, PlatformWalletOut, PlatformWalletTopupRequest, PlatformWalletTransactionOut,
)
from .security import encrypt_secret
from .services import DomainError, credit_platform_wallet, get_platform_company_info, log_activity, mask_mobile

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
    """secret_access_key is write-only, same convention as the SMTP password and ERPNext api_secret
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


@router.get("/erpnext-settings", response_model=PlatformErpNextSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_erpnext_settings_admin(db: Session = Depends(get_db)):
    row = db.get(PlatformErpNextSettings, "platform")
    if not row:
        row = PlatformErpNextSettings(id="platform")
    return PlatformErpNextSettingsOut(
        base_url=row.base_url, api_key=row.api_key, company=row.company,
        gst_tax_template=row.gst_tax_template, payment_account=row.payment_account, print_format=row.print_format,
        customer_group=row.customer_group, sales_invoice_naming_series=row.sales_invoice_naming_series,
        item_code_wallet_recharge=row.item_code_wallet_recharge, item_code_dlt_fee=row.item_code_dlt_fee,
        item_code_channel_subscription=row.item_code_channel_subscription, item_code_admin_credit=row.item_code_admin_credit,
        configured=bool(row.base_url and row.api_key and row.api_secret_encrypted and row.company),
    )


@router.put("/erpnext-settings", response_model=PlatformErpNextSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_erpnext_settings(payload: PlatformErpNextSettingsUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """api_secret is write-only, same convention as the SMTP password -- GET never returns it,
    and a blank value on PUT keeps whatever was already stored."""
    row = db.get(PlatformErpNextSettings, "platform")
    if not row:
        row = PlatformErpNextSettings(id="platform")
        db.add(row)
    row.base_url = payload.base_url
    row.api_key = payload.api_key
    if payload.api_secret:
        row.api_secret_encrypted = encrypt_secret(payload.api_secret)
    row.company = payload.company
    row.gst_tax_template = payload.gst_tax_template
    row.payment_account = payload.payment_account
    row.print_format = payload.print_format
    row.customer_group = payload.customer_group
    row.sales_invoice_naming_series = payload.sales_invoice_naming_series
    row.item_code_wallet_recharge = payload.item_code_wallet_recharge
    row.item_code_dlt_fee = payload.item_code_dlt_fee
    row.item_code_channel_subscription = payload.item_code_channel_subscription
    row.item_code_admin_credit = payload.item_code_admin_credit
    log_activity(db, None, "platform_erpnext_settings_updated", "Platform ERPNext settings updated.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(row)
    return PlatformErpNextSettingsOut(
        base_url=row.base_url, api_key=row.api_key, company=row.company,
        gst_tax_template=row.gst_tax_template, payment_account=row.payment_account, print_format=row.print_format,
        customer_group=row.customer_group, sales_invoice_naming_series=row.sales_invoice_naming_series,
        item_code_wallet_recharge=row.item_code_wallet_recharge, item_code_dlt_fee=row.item_code_dlt_fee,
        item_code_channel_subscription=row.item_code_channel_subscription, item_code_admin_credit=row.item_code_admin_credit,
        configured=bool(row.base_url and row.api_key and row.api_secret_encrypted and row.company),
    )


@router.get("/erpnext-accounts", response_model=list[ErpNextAccountOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_erpnext_accounts(db: Session = Depends(get_db)):
    """Real leaf accounts from the configured ERPNext company, for the payment-account dropdown --
    fetched live rather than free-typed, since (confirmed live, see the API reference doc) a
    group-node account name looks exactly as plausible as a real one but gets rejected the moment
    an invoice actually tries to use it."""
    settings_row = get_erpnext_settings(db)
    if not settings_row:
        raise HTTPException(status_code=422, detail="Configure the ERPNext base URL, API key/secret, and company first.")
    try:
        accounts = list_accounts(db, settings_row)
    except ErpNextCallError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch accounts from ERPNext: {exc}") from exc
    return [ErpNextAccountOut(name=a["name"], account_name=a["account_name"], account_type=a.get("account_type") or "") for a in accounts]


@router.get("/erpnext-tax-templates", response_model=list[ErpNextTaxTemplateOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_erpnext_tax_templates_admin(db: Session = Depends(get_db)):
    """Real Sales Taxes and Charges Templates from the configured ERPNext company, for the GST
    tax template dropdown -- referencing one by name is all Textzi needs to send; ERPNext computes
    and posts the correct CGST/SGST lines from the template's own setup."""
    settings_row = get_erpnext_settings(db)
    if not settings_row:
        raise HTTPException(status_code=422, detail="Configure the ERPNext base URL, API key/secret, and company first.")
    try:
        templates = list_tax_templates(db, settings_row)
    except ErpNextCallError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch tax templates from ERPNext: {exc}") from exc
    return [ErpNextTaxTemplateOut(name=t["name"], is_default=bool(t.get("is_default"))) for t in templates]


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
