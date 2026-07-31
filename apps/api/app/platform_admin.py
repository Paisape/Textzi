"""Admin-only configuration for the platform's own operational sending -- its SMS sender
identity, its SMTP config, and its wallet. Deliberately separate from every tenant-facing router:
this is Textzi's own infrastructure, not something any customer sees or touches."""
from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin import _caller_email, require_admin, require_admin_recent_2fa
from .database import get_db
from .models import PlatformErpNextSettings, PlatformGeneralSettings, PlatformSmsSettings, PlatformSmtpSettings, PlatformWallet, PlatformWalletTransaction
from .schemas import (
    PlatformErpNextSettingsOut, PlatformErpNextSettingsUpdate, PlatformGeneralSettingsOut, PlatformGeneralSettingsUpdate,
    PlatformSmsSettingsOut, PlatformSmsSettingsUpdate, PlatformSmtpSettingsOut, PlatformSmtpSettingsUpdate,
    PlatformWalletOut, PlatformWalletTopupRequest, PlatformWalletTransactionOut,
)
from .security import encrypt_secret
from .services import credit_platform_wallet, get_platform_company_info, log_activity

router = APIRouter(prefix="/v1/admin/platform", tags=["platform-admin"])


@router.get("/sms-settings", response_model=PlatformSmsSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_sms_settings(db: Session = Depends(get_db)):
    row = db.get(PlatformSmsSettings, "platform")
    if not row:
        row = PlatformSmsSettings(id="platform")
    return PlatformSmsSettingsOut(pe_id=row.pe_id, pe_operator=row.pe_operator, header_id=row.header_id, sender_id=row.sender_id, dlt_template_id=row.dlt_template_id, template_body=row.template_body, route=row.route)


@router.put("/sms-settings", response_model=PlatformSmsSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_sms_settings(payload: PlatformSmsSettingsUpdate, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
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
    log_activity(db, None, "platform_sms_settings_updated", "Platform SMS settings updated.", actor_email=_caller_email(authorization, db))
    db.commit(); db.refresh(row)
    return PlatformSmsSettingsOut(pe_id=row.pe_id, pe_operator=row.pe_operator, header_id=row.header_id, sender_id=row.sender_id, dlt_template_id=row.dlt_template_id, template_body=row.template_body, route=row.route)


@router.get("/smtp-settings", response_model=PlatformSmtpSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_smtp_settings(db: Session = Depends(get_db)):
    row = db.get(PlatformSmtpSettings, "platform")
    if not row:
        row = PlatformSmtpSettings(id="platform", port=587, from_address="no-reply@textzi.in", use_tls=True)
    return PlatformSmtpSettingsOut(host=row.host, port=row.port, username=row.username, from_address=row.from_address, use_tls=row.use_tls, configured=bool(row.host))


@router.put("/smtp-settings", response_model=PlatformSmtpSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_smtp_settings(payload: PlatformSmtpSettingsUpdate, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
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
    log_activity(db, None, "platform_smtp_settings_updated", "Platform SMTP settings updated.", actor_email=_caller_email(authorization, db))
    db.commit(); db.refresh(row)
    return PlatformSmtpSettingsOut(host=row.host, port=row.port, username=row.username, from_address=row.from_address, use_tls=row.use_tls, configured=bool(row.host))


@router.get("/erpnext-settings", response_model=PlatformErpNextSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_erpnext_settings_admin(db: Session = Depends(get_db)):
    row = db.get(PlatformErpNextSettings, "platform")
    if not row:
        # A transient (never-flushed) instance doesn't get its column-level `default=` applied --
        # that only happens at insert time -- so the two non-nullable fields need an explicit
        # value here or PlatformErpNextSettingsOut's own validation rejects the None.
        row = PlatformErpNextSettings(id="platform", customer_group="All Customer Groups", territory="All Territories")
    return PlatformErpNextSettingsOut(
        base_url=row.base_url, api_key=row.api_key, company=row.company,
        cgst_account_head=row.cgst_account_head, sgst_account_head=row.sgst_account_head, print_format=row.print_format,
        customer_group=row.customer_group, territory=row.territory,
        item_code_wallet_recharge=row.item_code_wallet_recharge, item_code_dlt_fee=row.item_code_dlt_fee,
        item_code_channel_subscription=row.item_code_channel_subscription, item_code_admin_credit=row.item_code_admin_credit,
        configured=bool(row.base_url and row.api_key and row.api_secret_encrypted and row.company),
    )


@router.put("/erpnext-settings", response_model=PlatformErpNextSettingsOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_erpnext_settings(payload: PlatformErpNextSettingsUpdate, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
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
    row.cgst_account_head = payload.cgst_account_head
    row.sgst_account_head = payload.sgst_account_head
    row.print_format = payload.print_format
    row.customer_group = payload.customer_group
    row.territory = payload.territory
    row.item_code_wallet_recharge = payload.item_code_wallet_recharge
    row.item_code_dlt_fee = payload.item_code_dlt_fee
    row.item_code_channel_subscription = payload.item_code_channel_subscription
    row.item_code_admin_credit = payload.item_code_admin_credit
    log_activity(db, None, "platform_erpnext_settings_updated", "Platform ERPNext settings updated.", actor_email=_caller_email(authorization, db))
    db.commit(); db.refresh(row)
    return PlatformErpNextSettingsOut(
        base_url=row.base_url, api_key=row.api_key, company=row.company,
        cgst_account_head=row.cgst_account_head, sgst_account_head=row.sgst_account_head, print_format=row.print_format,
        customer_group=row.customer_group, territory=row.territory,
        item_code_wallet_recharge=row.item_code_wallet_recharge, item_code_dlt_fee=row.item_code_dlt_fee,
        item_code_channel_subscription=row.item_code_channel_subscription, item_code_admin_credit=row.item_code_admin_credit,
        configured=bool(row.base_url and row.api_key and row.api_secret_encrypted and row.company),
    )


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
def update_general_settings(payload: PlatformGeneralSettingsUpdate, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
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
    log_activity(db, None, "platform_general_settings_updated", "Platform general settings updated.", actor_email=_caller_email(authorization, db))
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
def topup_wallet(payload: PlatformWalletTopupRequest, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    credit_platform_wallet(db, payload.amount, type="admin_topup", reference=payload.notes)
    log_activity(db, None, "platform_wallet_topup", f"Platform wallet topped up by {payload.amount} credits.", actor_email=_caller_email(authorization, db))
    db.commit()
    return get_wallet(db)
