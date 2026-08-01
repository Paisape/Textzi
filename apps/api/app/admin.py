import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
import jwt
import razorpay
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .auth import _issue_otp, STEP_UP_WINDOW_MINUTES
from .channels import _mark_dlt_request_paid
from .config import settings
from .database import get_db
from .email_service import render_email, send_email
from .erpnext import sync_invoice_to_erpnext
from .invoicing import create_draft_invoice, issue_invoice
from .models import (
    ADMIN_ROLES, AccountActivity, ApiKey, ChannelFeeConfig, ContactMessage, DeliveryAttempt, DeliveryStatusCodeRule, DltOnboardingRequest, DltOnboardingRequestDocument, EmailVerification, Entity,
    ErpNextApiCallLog, Header as HeaderModel, Invitation, Invoice, Message, Organization, PaymentOrder, PeId, PlatformMessage, PlatformWallet, PLATFORM_INTERNAL_ROLES, RateCard, RateCardSlab,
    Status as StatusEnum, Template, Testimonial, TwoFactorAuth, User, UserRateCard, UserRole, UserStatus, WabaWallet, Wallet, WalletTransaction,
)
from .schemas import (
    AdminAuditLogEntryOut, AdminCreateCustomerRequest, AdminCreateCustomerResponse, AdminInviteUserRequest, AdminMessageOut, AdminPlatformMessageOut, AdminResetPasswordResponse,
    ContactMessageAdminOut, TestimonialAdminCreateRequest, TestimonialAdminOut, TestimonialOut, TestimonialStatusUpdateRequest,
    ChannelFeeConfigOut, ChannelFeeConfigUpdate, CustomerAdminOut, DeliveryAttemptTelemetryOut, DeliveryStatusCodeRuleCreate, DeliveryStatusCodeRuleOut, DltDocumentOut, DltOnboardingRequestAdminOut,
    DltOnboardingRequestStatusUpdate, EntityAdminDetailOut, EntityCreate, EntityStatusUpdateRequest, ErpNextCallLogOut, ErpNextRetryResponse, HeaderAdminOut, HeaderCreate, InvoiceAdminOut, InvoiceOut,
    MessageTelemetryOut, NotificationOut, OrganizationOverviewResponse, PaymentDetailOut, PaymentOrderAdminOut, PaymentOrderReconcileResponse, PeCreate, PeIdAdminOut,
    PlatformMessageTelemetryOut, RateCardAssignmentOut, RateCardAssignmentRequest, RateCardCreate, RateCardMinRechargeUpdate, RateCardOut,
    RateCardPublicSettingsUpdate, RateCardSlabOut, RateCardSlabsReplace, RechargeDetailOut, TeamInviteResponse, TeamMemberOut, TemplateAdminDetailOut, TemplateCreate,
    TwoFactorAdminUpdate, TwoFactorStatusOut, UsageOrgBreakdown, UsageSummaryResponse, UserAdminOut,
    UserRoleUpdateRequest, UserStatusUpdateRequest, WalletCreditRequest, WalletCreditResponse,
)
from .security import decode_access_token, decrypt_recipient_lenient, hash_api_key, hash_password
from .services import GST_RATE, DomainError, credit_wallet, log_activity, mask_mobile, quote_credits, rate_card_slabs, redact_otp, resolve_primary_user, resolve_rate_card
from .team import INVITE_TTL_HOURS

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def require_admin(x_admin_key: str | None = Header(default=None), authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Accepts either the bootstrap X-Admin-Key (for scripting/curl) or a Bearer token belonging
    to a logged-in user with an admin-tier role (Super Admin / Operator Admin), for a real admin
    login through the normal auth flow."""
    if x_admin_key:
        if settings.environment != "development" and settings.admin_bootstrap_key.startswith("development-"):
            raise HTTPException(status_code=503, detail="Admin key is not configured")
        if hmac.compare_digest(x_admin_key, settings.admin_bootstrap_key):
            return

    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
            user = db.get(User, claims.get("sub"))
            if user and user.role in ADMIN_ROLES and user.status == UserStatus.active:
                return
        except jwt.PyJWTError:
            pass

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin access required: provide X-Admin-Key or log in with an admin account")


def _caller_email(authorization: str | None, db: Session) -> str:
    """Best-effort actor identity for audit-log entries on admin endpoints that don't otherwise
    need the caller's identity for authorization decisions -- falls back to a label rather than
    raising, since these endpoints already trust require_admin/the bootstrap key to have gated
    access; this is purely for attribution, not authorization."""
    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
            user = db.get(User, claims.get("sub"))
            if user:
                return user.email
        except jwt.PyJWTError:
            pass
    return "admin (bootstrap key)"


def require_admin_recent_2fa(x_admin_key: str | None = Header(default=None), authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Stacks alongside require_admin on the admin Settings-group endpoints. The bootstrap
    X-Admin-Key already fully authenticates independent of any single user's identity, so it
    skips this check entirely -- same bypass require_admin itself grants it. A real admin-user
    JWT session additionally needs the same step-up freshness as require_recent_2fa (auth.py),
    but only if that admin has 2FA enabled -- opt-in, no behavior change otherwise."""
    if x_admin_key and hmac.compare_digest(x_admin_key, settings.admin_bootstrap_key):
        return
    if not authorization or not authorization.startswith("Bearer "):
        return  # require_admin (the sibling dependency) already rejects this case
    try:
        claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
    except jwt.PyJWTError:
        return  # ditto
    user = db.get(User, claims.get("sub"))
    if not user:
        return
    two_factor = db.get(TwoFactorAuth, user.id)
    if not two_factor or not two_factor.enabled:
        return
    verified_at = claims.get("mfa_verified_at")
    enabled_at_ts = two_factor.enabled_at.timestamp() if two_factor.enabled_at else 0
    if not verified_at or verified_at < enabled_at_ts or datetime.now(timezone.utc).timestamp() - verified_at > STEP_UP_WINDOW_MINUTES * 60:
        raise HTTPException(status_code=401, detail="step_up_required")


@router.get("/organizations", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_organizations(db: Session = Depends(get_db)):
    orgs = db.scalars(select(Organization).order_by(Organization.name)).all()
    return [{"id": o.id, "name": o.name, "gstin": o.gstin, "pan": o.pan, "industry": o.industry, "address": o.address} for o in orgs]


@router.post("/organizations", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_organization(name: str, db: Session = Depends(get_db)):
    item = Organization(name=name)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name}


@router.get("/entities", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_entities(organization_id: str | None = None, db: Session = Depends(get_db)):
    query = select(Entity).order_by(Entity.name)
    if organization_id:
        query = query.where(Entity.organization_id == organization_id)
    entities = db.scalars(query).all()
    return [{"id": e.id, "organization_id": e.organization_id, "name": e.name, "status": e.status} for e in entities]


@router.post("/entities", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_entity(payload: EntityCreate, db: Session = Depends(get_db)):
    if not db.get(Organization, payload.organization_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    entity = Entity(**payload.model_dump(), status=StatusEnum.active)
    db.add(entity); db.flush()
    db.add(Wallet(entity_id=entity.id, prepaid_balance=0, credit_limit=0, credit_used=0))
    db.add(WabaWallet(entity_id=entity.id, prepaid_balance=0, credit_limit=0, credit_used=0))
    db.commit(); db.refresh(entity)
    return {"id": entity.id, "name": entity.name, "status": entity.status}


@router.post("/entities/{entity_id}/pe-ids", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_pe(entity_id: str, payload: PeCreate, db: Session = Depends(get_db)):
    if not db.get(Entity, entity_id): raise HTTPException(status_code=404, detail="Entity not found")
    item = PeId(entity_id=entity_id, **payload.model_dump(), status=StatusEnum.active)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "value": item.value, "status": item.status}


@router.post("/pe-ids/{pe_id}/headers", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_header(pe_id: str, payload: HeaderCreate, db: Session = Depends(get_db)):
    if not db.get(PeId, pe_id): raise HTTPException(status_code=404, detail="PE ID not found")
    item = HeaderModel(pe_id=pe_id, **payload.model_dump(), status=StatusEnum.active)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "value": item.value, "status": item.status}


@router.post("/entities/{entity_id}/templates", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_template(entity_id: str, payload: TemplateCreate, db: Session = Depends(get_db)):
    pe, header = db.get(PeId, payload.pe_id), db.get(HeaderModel, payload.header_id)
    if not pe or pe.entity_id != entity_id or not header or header.pe_id != pe.id:
        raise HTTPException(status_code=422, detail="Template PE/Header mapping is invalid")
    item = Template(entity_id=entity_id, pe_id=payload.pe_id, header_id=payload.header_id, alias=payload.alias, dlt_template_id=payload.dlt_template_id, body=payload.body, category=payload.category.value, status=StatusEnum.active)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A template with alias '{payload.alias}' or DLT template id '{payload.dlt_template_id}' already exists for this entity")
    db.refresh(item)
    return {"id": item.id, "alias": item.alias, "dlt_template_id": item.dlt_template_id, "category": item.category}


@router.get("/entities/{entity_id}/api-keys", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_api_keys(entity_id: str, db: Session = Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.entity_id == entity_id)).all()
    return [{"id": k.id, "active": k.active} for k in keys]


@router.post("/entities/{entity_id}/api-keys", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_api_key(entity_id: str, db: Session = Depends(get_db)):
    # Minting a live API key for a customer entity is exactly as sensitive here as it is on the
    # self-service path (channels.py's POST /api-keys, which requires a freshly-issued OTP on top
    # of this same 2FA step-up) -- this admin path must never be the softer way to get the same
    # capability, or it's a standing bypass of that entire OTP-gated feature.
    if not db.get(Entity, entity_id): raise HTTPException(status_code=404, detail="Entity not found")
    raw_key = "pk_live_" + secrets.token_urlsafe(32)
    item = ApiKey(entity_id=entity_id, key_hash=hash_api_key(raw_key), active=True)
    db.add(item); db.commit()
    return {"api_key": raw_key, "warning": "Store this key securely; it will not be shown again."}


@router.get("/entities/{entity_id}/dlt-assets", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_dlt_assets(entity_id: str, db: Session = Depends(get_db)):
    pes = db.scalars(select(PeId).where(PeId.entity_id == entity_id)).all()
    headers = db.scalars(select(HeaderModel).join(PeId).where(PeId.entity_id == entity_id)).all()
    templates = db.scalars(select(Template).where(Template.entity_id == entity_id)).all()
    return {
        "pe_ids": [{"id": x.id, "value": x.value, "operator": x.operator, "status": x.status} for x in pes],
        "headers": [{"id": x.id, "pe_id": x.pe_id, "header_id": x.header_id, "value": x.value, "status": x.status} for x in headers],
        "templates": [{"id": x.id, "pe_id": x.pe_id, "header_id": x.header_id, "alias": x.alias, "dlt_template_id": x.dlt_template_id, "body": x.body, "category": x.category, "status": x.status} for x in templates],
    }


def _rate_card_out(db: Session, card: RateCard) -> RateCardOut:
    slabs = rate_card_slabs(db, card.id)
    return RateCardOut(
        id=card.id,
        name=card.name,
        channel=card.channel,
        is_default=card.is_default,
        min_recharge_amount=float(card.min_recharge_amount),
        show_on_public_pricing=card.show_on_public_pricing,
        public_tagline=card.public_tagline,
        slabs=[RateCardSlabOut(id=s.id, min_amount=float(s.min_amount), max_amount=float(s.max_amount) if s.max_amount is not None else None, price_per_sms=float(s.price_per_sms)) for s in slabs],
    )


def _validate_slabs(slabs: list) -> None:
    for slab in slabs:
        if slab.max_amount is not None and slab.max_amount <= slab.min_amount:
            raise HTTPException(status_code=422, detail=f"A slab's max_amount ({slab.max_amount}) must be greater than its min_amount ({slab.min_amount})")
    ordered = sorted(slabs, key=lambda s: s.min_amount)
    for current, following in zip(ordered, ordered[1:]):
        if current.max_amount is None or current.max_amount > following.min_amount:
            raise HTTPException(status_code=422, detail="Rate card slabs must not overlap -- check the min/max amount ranges")


@router.get("/rate-cards", response_model=list[RateCardOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_rate_cards(db: Session = Depends(get_db)):
    cards = db.scalars(select(RateCard).order_by(RateCard.created_at)).all()
    return [_rate_card_out(db, c) for c in cards]


@router.post("/rate-cards", response_model=RateCardOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_rate_card(payload: RateCardCreate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if db.scalar(select(RateCard).where(RateCard.name == payload.name)):
        raise HTTPException(status_code=409, detail=f"A rate card named '{payload.name}' already exists")
    _validate_slabs(payload.slabs)
    is_first_card_of_channel = db.scalar(select(RateCard).where(RateCard.channel == payload.channel).limit(1)) is None
    card = RateCard(name=payload.name, channel=payload.channel, is_default=is_first_card_of_channel and payload.channel == "sms", min_recharge_amount=payload.min_recharge_amount)
    db.add(card); db.flush()
    for slab in payload.slabs:
        db.add(RateCardSlab(rate_card_id=card.id, min_amount=slab.min_amount, max_amount=slab.max_amount, price_per_sms=slab.price_per_sms))
    log_activity(db, None, "rate_card_created", f"Rate card '{payload.name}' created.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(card)
    return _rate_card_out(db, card)


@router.put("/rate-cards/{card_id}/slabs", response_model=RateCardOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def replace_rate_card_slabs(card_id: str, payload: RateCardSlabsReplace, db: Session = Depends(get_db)):
    card = db.get(RateCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    _validate_slabs(payload.slabs)
    for existing in rate_card_slabs(db, card_id):
        db.delete(existing)
    db.flush()
    for slab in payload.slabs:
        db.add(RateCardSlab(rate_card_id=card.id, min_amount=slab.min_amount, max_amount=slab.max_amount, price_per_sms=slab.price_per_sms))
    db.commit(); db.refresh(card)
    return _rate_card_out(db, card)


@router.put("/rate-cards/{card_id}/min-recharge", response_model=RateCardOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_rate_card_min_recharge(card_id: str, payload: RateCardMinRechargeUpdate, db: Session = Depends(get_db)):
    card = db.get(RateCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    card.min_recharge_amount = payload.min_recharge_amount
    db.commit(); db.refresh(card)
    return _rate_card_out(db, card)


@router.post("/rate-cards/{card_id}/set-default", response_model=RateCardOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def set_default_rate_card(card_id: str, db: Session = Depends(get_db)):
    card = db.get(RateCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    if card.channel != "sms":
        raise HTTPException(status_code=422, detail="Only SMS-channel rate cards can be set as default -- other channels are for public-pricing display only, real billing isn't slab-priced for them yet")
    for other in db.scalars(select(RateCard).where(RateCard.is_default == True, RateCard.channel == "sms")).all():  # noqa: E712
        other.is_default = False
    card.is_default = True
    db.commit(); db.refresh(card)
    return _rate_card_out(db, card)


@router.put("/rate-cards/{card_id}/public-settings", response_model=RateCardOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_rate_card_public_settings(card_id: str, payload: RateCardPublicSettingsUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Controls whether/how this card appears on the public marketing site's Pricing section."""
    card = db.get(RateCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    card.show_on_public_pricing = payload.show_on_public_pricing
    card.public_tagline = payload.public_tagline
    log_activity(db, None, "rate_card_public_settings_updated", f"Rate card '{card.name}' public-pricing visibility set to {payload.show_on_public_pricing}.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(card)
    return _rate_card_out(db, card)


@router.delete("/rate-cards/{card_id}", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def delete_rate_card(card_id: str, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    card = db.get(RateCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    if card.is_default:
        raise HTTPException(status_code=422, detail="Cannot delete the default rate card — set another card as default first")
    for assignment in db.scalars(select(UserRateCard).where(UserRateCard.rate_card_id == card_id)).all():
        db.delete(assignment)
    for slab in rate_card_slabs(db, card_id):
        db.delete(slab)
    # Flush before deleting the card itself -- there's no relationship() between RateCard and
    # RateCardSlab (just a raw FK column), so SQLAlchemy's automatic dependency-based delete
    # ordering doesn't apply here; without this flush the card's DELETE can be issued before the
    # slabs' DELETEs, violating rate_card_slabs_rate_card_id_fkey.
    db.flush()
    log_activity(db, None, "rate_card_deleted", f"Rate card '{card.name}' deleted.", actor_email=_caller_email(authorization, db), request=request)
    db.delete(card)
    db.commit()
    return {"id": card_id, "removed": True}


@router.get("/rate-cards/assignments", response_model=list[RateCardAssignmentOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_rate_card_assignments(db: Session = Depends(get_db)):
    assignments = db.scalars(select(UserRateCard)).all()
    out = []
    for a in assignments:
        user = db.get(User, a.user_id)
        card = db.get(RateCard, a.rate_card_id)
        if user and card:
            out.append(RateCardAssignmentOut(user_id=user.id, user_email=user.email, rate_card_id=card.id, rate_card_name=card.name))
    return out


@router.post("/rate-cards/assignments", response_model=RateCardAssignmentOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def upsert_rate_card_assignment(payload: RateCardAssignmentRequest, db: Session = Depends(get_db)):
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    card = db.get(RateCard, payload.rate_card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Rate card not found")
    assignment = db.get(UserRateCard, payload.user_id)
    if assignment:
        assignment.rate_card_id = card.id
    else:
        assignment = UserRateCard(user_id=payload.user_id, rate_card_id=card.id)
        db.add(assignment)
    db.commit()
    return RateCardAssignmentOut(user_id=user.id, user_email=user.email, rate_card_id=card.id, rate_card_name=card.name)


@router.delete("/rate-cards/assignments/{user_id}", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def delete_rate_card_assignment(user_id: str, db: Session = Depends(get_db)):
    assignment = db.get(UserRateCard, user_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="No custom rate card assignment for this user")
    db.delete(assignment)
    db.commit()
    return {"user_id": user_id, "removed": True}


@router.get("/channel-fees/{channel}", response_model=ChannelFeeConfigOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_channel_fees(channel: str, db: Session = Depends(get_db)):
    fees = db.get(ChannelFeeConfig, channel)
    if not fees:
        raise HTTPException(status_code=404, detail=f"No fee configuration exists for channel '{channel}'")
    return ChannelFeeConfigOut(channel=fees.channel, subscription_price=float(fees.subscription_price), dlt_platform_fee=float(fees.dlt_platform_fee), dlt_service_fee=float(fees.dlt_service_fee))


@router.put("/channel-fees/{channel}", response_model=ChannelFeeConfigOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_channel_fees(channel: str, payload: ChannelFeeConfigUpdate, db: Session = Depends(get_db)):
    fees = db.get(ChannelFeeConfig, channel)
    if not fees:
        fees = ChannelFeeConfig(channel=channel)
        db.add(fees)
    fees.subscription_price = payload.subscription_price
    fees.dlt_platform_fee = payload.dlt_platform_fee
    fees.dlt_service_fee = payload.dlt_service_fee
    db.commit(); db.refresh(fees)
    return ChannelFeeConfigOut(channel=fees.channel, subscription_price=float(fees.subscription_price), dlt_platform_fee=float(fees.dlt_platform_fee), dlt_service_fee=float(fees.dlt_service_fee))


@router.get("/delivery-status-rules", response_model=list[DeliveryStatusCodeRuleOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_delivery_status_rules(db: Session = Depends(get_db)):
    """Every DeliveryStatusCode NOT listed here defaults to a billable success -- only codes an
    admin explicitly adds are treated as a failed send when a DR webhook reports them."""
    rows = db.scalars(select(DeliveryStatusCodeRule).order_by(DeliveryStatusCodeRule.code)).all()
    return [DeliveryStatusCodeRuleOut(code=r.code, label=r.label, refund=r.refund) for r in rows]


@router.post("/delivery-status-rules", response_model=DeliveryStatusCodeRuleOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def upsert_delivery_status_rule(payload: DeliveryStatusCodeRuleCreate, db: Session = Depends(get_db)):
    row = db.get(DeliveryStatusCodeRule, payload.code)
    if not row:
        row = DeliveryStatusCodeRule(code=payload.code)
        db.add(row)
    row.label = payload.label
    row.refund = payload.refund
    db.commit(); db.refresh(row)
    return DeliveryStatusCodeRuleOut(code=row.code, label=row.label, refund=row.refund)


@router.delete("/delivery-status-rules/{code}", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def delete_delivery_status_rule(code: int, db: Session = Depends(get_db)):
    row = db.get(DeliveryStatusCodeRule, code)
    if not row:
        raise HTTPException(status_code=404, detail=f"No rule configured for status code {code}")
    db.delete(row)
    db.commit()
    return {"code": code, "removed": True}


def _dlt_request_admin_out(db: Session, r: DltOnboardingRequest) -> DltOnboardingRequestAdminOut:
    entity = db.get(Entity, r.entity_id)
    org = db.get(Organization, entity.organization_id) if entity else None
    docs = db.scalars(select(DltOnboardingRequestDocument).where(DltOnboardingRequestDocument.request_id == r.id)).all()
    return DltOnboardingRequestAdminOut(
        id=r.id, status=r.status, notes=r.notes, total_amount=float(r.total_amount), created_at=r.created_at.isoformat(),
        documents=[DltDocumentOut(id=d.id, filename=d.filename) for d in docs],
        entity_id=r.entity_id, entity_name=entity.name if entity else "(deleted entity)",
        organization_name=org.name if org else "(deleted organization)",
    )


@router.get("/dlt-requests", response_model=list[DltOnboardingRequestAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_dlt_requests(request_status: str | None = None, entity_id: str | None = None, db: Session = Depends(get_db)):
    query = select(DltOnboardingRequest).order_by(DltOnboardingRequest.created_at.desc())
    if request_status:
        query = query.where(DltOnboardingRequest.status == request_status)
    if entity_id:
        query = query.where(DltOnboardingRequest.entity_id == entity_id)
    requests = db.scalars(query).all()
    return [_dlt_request_admin_out(db, r) for r in requests]


@router.patch("/dlt-requests/{request_id}", response_model=DltOnboardingRequestAdminOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_dlt_request_status(request_id: str, payload: DltOnboardingRequestStatusUpdate, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    request_row = db.get(DltOnboardingRequest, request_id)
    if not request_row:
        raise HTTPException(status_code=404, detail="DLT registration request not found")
    entity = db.get(Entity, request_row.entity_id)
    old_status = request_row.status
    request_row.status = payload.status
    log_activity(db, entity.organization_id if entity else None, "dlt_request_status_changed", f"DLT request status changed from {old_status} to {payload.status}.", actor_email=_caller_email(authorization, db), request=request)
    db.commit(); db.refresh(request_row)
    return _dlt_request_admin_out(db, request_row)


@router.get("/dlt-requests/{request_id}/documents/{doc_id}", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def download_dlt_request_document(request_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = db.get(DltOnboardingRequestDocument, doc_id)
    if not doc or doc.request_id != request_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(doc.stored_path, filename=doc.filename)


def _user_admin_out(db: Session, user: User) -> UserAdminOut:
    two_factor = db.get(TwoFactorAuth, user.id)
    return UserAdminOut(
        id=user.id, email=user.email, full_name=user.full_name, role=user.role, status=user.status,
        organization_id=user.organization_id, email_verified=user.email_verified, mobile_verified=user.mobile_verified,
        two_factor_enabled=bool(two_factor and two_factor.enabled),
    )


@router.get("/users", response_model=list[UserAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_users(search: str | None = None, db: Session = Depends(get_db)):
    """Platform staff only -- every tenant/customer-side account (enterprise_customer, sub_user,
    finance_user, marketing_user, read_only_user) is managed instead through /admin/customers,
    since mixing the two together made it unclear which "users" a given search result even
    referred to."""
    query = select(User).where(User.role.in_(PLATFORM_INTERNAL_ROLES)).order_by(User.email)
    if search:
        like = f"%{search}%"
        query = query.where(or_(User.full_name.ilike(like), User.email.ilike(like)))
    users = db.scalars(query).all()
    user_ids = [u.id for u in users]
    two_factor_enabled_ids = {tf.user_id for tf in db.scalars(select(TwoFactorAuth).where(TwoFactorAuth.user_id.in_(user_ids), TwoFactorAuth.enabled == True)).all()} if user_ids else set()  # noqa: E712
    return [UserAdminOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, status=u.status, organization_id=u.organization_id, email_verified=u.email_verified, mobile_verified=u.mobile_verified, two_factor_enabled=u.id in two_factor_enabled_ids) for u in users]


@router.get("/customer-users", response_model=list[UserAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_customer_users(search: str | None = None, db: Session = Depends(get_db)):
    """The customer-side counterpart to list_users -- every user belonging to an organization
    (enterprise_customer, sub_user, finance_user, marketing_user, read_only_user), for pickers
    like Rate Cards' per-user assignment that need an individual customer user, not an
    organization row (which is all /admin/customers returns)."""
    query = select(User).where(User.organization_id.is_not(None)).order_by(User.email)
    if search:
        like = f"%{search}%"
        query = query.where(or_(User.full_name.ilike(like), User.email.ilike(like)))
    users = db.scalars(query).all()
    return [UserAdminOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, status=u.status, organization_id=u.organization_id, email_verified=u.email_verified, mobile_verified=u.mobile_verified, two_factor_enabled=False) for u in users]


@router.post("/users/invite", response_model=TeamInviteResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def invite_staff_user(payload: AdminInviteUserRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Invites a new platform-staff account -- the only other ways any account comes into
    existence are self-registration (always enterprise_customer) or a team invite (always one of
    the customer-side sub-roles), neither of which can produce an internal-tier account. Mirrors
    /v1/team/invite's shape: the admin only picks email + role, and the invitee fills in their own
    name, mobile number, and password when they accept -- same shared Invitation row and
    /v1/team/accept-invite endpoint as a customer team invite, just with organization_id left
    null.

    Deliberately restricted to ADMIN_ROLES, not the wider PLATFORM_INTERNAL_ROLES: require_admin
    (every admin-panel endpoint) and the frontend's nav split both only recognize
    super_admin/operator_admin as "admin" today. finance_team/support_team/sales_team/
    reseller/agency/developer are role values with broad capability grants but no admin-panel UI
    or route access wired up -- inviting someone into one of those would create an account with
    nowhere to go after logging in. Same admin-tier protection as update_user_role: granting
    super_admin/operator_admin requires the caller themselves be Super Admin."""
    if payload.role.value not in ADMIN_ROLES:
        raise HTTPException(status_code=422, detail="Only Super Admin or Operator Admin can be invited here -- the other internal roles have no admin-panel access wired up yet")
    caller = None
    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
            caller = db.get(User, claims.get("sub"))
        except jwt.PyJWTError:
            caller = None
    if payload.role.value in ADMIN_ROLES and caller and caller.role != UserRole.super_admin.value:
        raise HTTPException(status_code=403, detail="Only Super Admin can invite an admin-tier role")
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=None, email=payload.email, invited_by_user_id=caller.id if caller else None,
        token_hash=hash_api_key(token), role=payload.role.value,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS),
    )
    db.add(invitation)
    db.commit()

    accept_url = f"{settings.web_origin}/accept-invite?token={token}"
    send_email(
        db,
        to=payload.email,
        subject="You've been invited to join the Textzi team",
        html_body=render_email(
            "You've been invited to Textzi",
            f"<p>You've been invited to join the Textzi platform team as <b>{payload.role.value.replace('_', ' ').title()}</b>.</p>"
            f"<p>Click below to set up your account. This invite expires in {INVITE_TTL_HOURS} hours.</p>",
            cta_label="Accept Invite",
            cta_url=accept_url,
        ),
    )
    return TeamInviteResponse(invitation_id=invitation.id, email=invitation.email, dev_invite_token=token if settings.environment == "development" else None)


@router.patch("/users/{user_id}/role", response_model=UserAdminOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_user_role(user_id: str, payload: UserRoleUpdateRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """No self-role-change (even a legitimate admin acting on their own account here is
    indistinguishable from a stolen-token attacker granting themself more privilege -- a peer
    admin must make this change instead), and only an existing Super Admin can grant OR REVOKE
    an admin-tier role -- checking only the requested new role (not the target's current one)
    would let an operator_admin freely de-admin a super_admin by "promoting" them to an ordinary
    role, since that new role itself isn't admin-tier. The bootstrap X-Admin-Key path (caller is
    None here) is already maximally trusted and skips both checks, same as require_admin's own
    bypass."""
    caller = None
    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
            caller = db.get(User, claims.get("sub"))
        except jwt.PyJWTError:
            caller = None
    if caller and caller.id == user_id:
        raise HTTPException(status_code=422, detail="You cannot change your own role -- ask another admin to make this change")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    touches_admin_tier = payload.role.value in ADMIN_ROLES or user.role in ADMIN_ROLES
    if touches_admin_tier and caller and caller.role != UserRole.super_admin.value:
        raise HTTPException(status_code=403, detail="Only Super Admin can grant or revoke an admin-tier role")
    old_role = user.role
    user.role = payload.role.value
    log_activity(db, user.organization_id, "role_changed", f"{user.email}'s role changed from {old_role.replace('_', ' ')} to {payload.role.value.replace('_', ' ')}.", user_id=user.id, actor_email=caller.email if caller else "admin (bootstrap key)", request=request)
    db.commit(); db.refresh(user)
    return _user_admin_out(db, user)


@router.patch("/users/{user_id}/two-factor", response_model=TwoFactorStatusOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def admin_update_two_factor(user_id: str, payload: TwoFactorAdminUpdate, db: Session = Depends(get_db)):
    """Recovery lever for a locked-out user (e.g. lost authenticator device) -- admin-only
    force-disable, no backup codes in this pass. Enabling 2FA for someone else is not supported
    since only the user can prove possession of the secret via a live code."""
    if payload.enabled:
        raise HTTPException(status_code=422, detail="2FA can only be enabled by the user themselves")
    row = db.get(TwoFactorAuth, user_id)
    if row:
        db.delete(row)
        db.commit()
    return TwoFactorStatusOut(enabled=False)


@router.post("/users/{user_id}/reset-password", response_model=AdminResetPasswordResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def admin_reset_password(user_id: str, request: Request, db: Session = Depends(get_db)):
    """The only way a platform-staff account's password ever gets reset -- forgot_password
    (auth.py) refuses staff outright, by design. Generates a fresh random password, emails it,
    and clears any login lockout so the reset itself isn't immediately unusable."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    generated_password = secrets.token_urlsafe(9)
    user.password_hash = hash_password(generated_password)
    user.failed_login_attempts = 0
    user.login_locked_until = None
    log_activity(db, user.organization_id, "password_reset_by_admin", f"{user.email}'s password was reset by an admin.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()
    send_email(
        db,
        to=user.email,
        subject="Your Textzi password has been reset",
        html_body=render_email(
            "Your password has been reset",
            f"<p>Hi {user.full_name},</p><p>An admin reset your Textzi account password. Your new temporary password is below -- sign in and consider changing it from Account Security.</p>"
            f"<p style=\"margin:24px 0; text-align:center;\"><span style=\"display:inline-block; font-size:20px; font-weight:bold; letter-spacing:1px; color:#1a1a1a; background:#f4f4f5; padding:12px 24px; border-radius:6px;\">{generated_password}</span></p>",
        ),
    )
    return AdminResetPasswordResponse(
        message=f"Password reset. A new temporary password has been emailed to {user.email}.",
        dev_generated_password=generated_password if settings.environment == "development" else None,
    )


@router.patch("/users/{user_id}/status", response_model=UserAdminOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_user_status(user_id: str, payload: UserStatusUpdateRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Suspend/reactivate any account (staff or customer) -- same self-action and admin-tier
    protections as update_user_role, since suspending is just as capable of being used for
    privilege abuse as a role change is (a stolen operator_admin token suspending the one
    super_admin who could undo it, for instance)."""
    caller = None
    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
            caller = db.get(User, claims.get("sub"))
        except jwt.PyJWTError:
            caller = None
    if caller and caller.id == user_id:
        raise HTTPException(status_code=422, detail="You cannot suspend your own account -- ask another admin to make this change")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role in ADMIN_ROLES and caller and caller.role != UserRole.super_admin.value:
        raise HTTPException(status_code=403, detail="Only Super Admin can suspend or reactivate an admin-tier account")
    old_status = user.status
    user.status = payload.status
    if payload.status == UserStatus.active:
        user.failed_login_attempts = 0
        user.login_locked_until = None
    log_activity(db, user.organization_id, "status_changed", f"{user.email}'s status changed from {old_status.value.replace('_', ' ')} to {payload.status.value.replace('_', ' ')}.", user_id=user.id, actor_email=caller.email if caller else "admin (bootstrap key)", request=request)
    db.commit(); db.refresh(user)
    return _user_admin_out(db, user)


@router.patch("/entities/{entity_id}/status", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_entity_status(entity_id: str, payload: EntityStatusUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """Deactivating an entity doesn't touch its users' logins -- it stops that entity's own
    sending (require_channel_active-style checks live at dispatch time, not here) without
    suspending the people who manage it."""
    entity = db.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity.status = payload.status
    log_activity(db, entity.organization_id, "entity_status_changed", f"Entity '{entity.name}' status changed to {payload.status.value}.", actor_email="admin", request=request)
    db.commit(); db.refresh(entity)
    return {"id": entity.id, "name": entity.name, "status": entity.status}


def _invoice_out(invoice: Invoice) -> InvoiceOut:
    return InvoiceOut(
        id=invoice.id, entity_id=invoice.entity_id, invoice_number=invoice.invoice_number, type=invoice.type,
        status=invoice.status, base_amount=float(invoice.base_amount), gst_amount=float(invoice.gst_amount),
        total_amount=float(invoice.total_amount), reference=invoice.reference, notes=invoice.notes,
        created_at=invoice.created_at.isoformat(), issued_at=invoice.issued_at.isoformat() if invoice.issued_at else None,
    )


def _invoice_admin_out(db: Session, invoice: Invoice) -> InvoiceAdminOut:
    entity = db.get(Entity, invoice.entity_id)
    org = db.get(Organization, entity.organization_id) if entity else None
    base = _invoice_out(invoice)
    return InvoiceAdminOut(**base.model_dump(), entity_name=entity.name if entity else "(deleted entity)", organization_name=org.name if org else "(deleted organization)")


@router.get("/invoices", response_model=list[InvoiceAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_all_invoices(invoice_status: str | None = None, entity_id: str | None = None, db: Session = Depends(get_db)):
    query = select(Invoice).order_by(Invoice.created_at.desc())
    if invoice_status:
        query = query.where(Invoice.status == invoice_status)
    if entity_id:
        query = query.where(Invoice.entity_id == entity_id)
    invoices = db.scalars(query).all()
    return [_invoice_admin_out(db, i) for i in invoices]


@router.get("/invoices/{invoice_id}/pdf", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def download_invoice_admin(invoice_id: str, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice or not invoice.pdf_path:
        raise HTTPException(status_code=404, detail="Invoice not found, or still a draft (issue it first)")
    return FileResponse(invoice.pdf_path, filename=f"{invoice.invoice_number}.pdf", media_type="application/pdf")


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceAdminOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def issue_invoice_admin(invoice_id: str, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == "issued":
        raise HTTPException(status_code=409, detail="This invoice has already been issued")
    issue_invoice(db, invoice)
    entity = db.get(Entity, invoice.entity_id)
    log_activity(db, entity.organization_id if entity else None, "invoice_issued_by_admin", f"Invoice for entity issued (Rs.{float(invoice.total_amount):.2f}).", actor_email=_caller_email(authorization, db), request=request)
    db.commit()
    db.refresh(invoice)
    return _invoice_admin_out(db, invoice)


@router.post("/invoices/issue-all-drafts", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def bulk_issue_draft_invoices(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    drafts = db.scalars(select(Invoice).where(Invoice.status == "draft")).all()
    for invoice in drafts:
        issue_invoice(db, invoice)
    if drafts:
        log_activity(db, None, "bulk_invoices_issued", f"{len(drafts)} draft invoice(s) issued in bulk.", actor_email=_caller_email(authorization, db), request=request)
    db.commit()
    return {"issued_count": len(drafts)}


@router.post("/invoices/{invoice_id}/retry-erpnext-sync", response_model=ErpNextRetryResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def retry_erpnext_sync(invoice_id: str, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Re-attempts the exact same Customer/Item/Sales-Invoice/PDF-fetch chain issue_invoice tried
    -- for an invoice that was already issued (with Textzi's own fallback PDF, if the first
    attempt failed) once whatever caused the original failure has been fixed. On success, the
    stored PDF is replaced with the ERPNext-generated one; on failure, the invoice keeps its
    current PDF and erpnext_sync_error is updated with the new reason."""
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "issued":
        raise HTTPException(status_code=409, detail="This invoice hasn't been issued yet")
    entity = db.get(Entity, invoice.entity_id)
    organization = db.get(Organization, entity.organization_id) if entity else None
    if not organization:
        raise HTTPException(status_code=422, detail="Could not resolve this invoice's organization")

    pdf_bytes = sync_invoice_to_erpnext(db, invoice, organization)
    if pdf_bytes is not None:
        directory = os.path.join(settings.uploads_dir, "invoices")
        os.makedirs(directory, exist_ok=True)
        pdf_path = os.path.join(directory, f"{invoice.id}.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        invoice.pdf_path = pdf_path
        db.commit()

    log_activity(
        db, entity.organization_id if entity else None, "erpnext_sync_retried",
        f"ERPNext sync retried for invoice {invoice.invoice_number} -- {invoice.erpnext_sync_status}.",
        actor_email=_caller_email(authorization, db), request=request,
    )
    db.refresh(invoice)
    return ErpNextRetryResponse(
        invoice_id=invoice.id, erpnext_sync_status=invoice.erpnext_sync_status,
        erpnext_invoice_name=invoice.erpnext_invoice_name, erpnext_sync_error=invoice.erpnext_sync_error,
    )


@router.get("/erpnext/call-log", response_model=list[ErpNextCallLogOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_erpnext_call_log(status_filter: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    query = select(ErpNextApiCallLog).order_by(ErpNextApiCallLog.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(ErpNextApiCallLog.status == status_filter)
    rows = db.scalars(query).all()
    invoice_ids = {r.invoice_id for r in rows if r.invoice_id}
    invoice_numbers = {}
    if invoice_ids:
        for inv in db.scalars(select(Invoice).where(Invoice.id.in_(invoice_ids))).all():
            invoice_numbers[inv.id] = inv.invoice_number
    return [
        ErpNextCallLogOut(
            id=r.id, invoice_id=r.invoice_id, invoice_number=invoice_numbers.get(r.invoice_id) if r.invoice_id else None,
            method=r.method, path=r.path, status=r.status, status_code=r.status_code, error=r.error,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.post("/wallet-credits", response_model=WalletCreditResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_wallet_credit(payload: WalletCreditRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Admin manual SMS credit. `amount` is rupees, converted to credits via the target entity's
    own assigned rate card (same conversion as self-service recharge). Always creates a draft
    invoice for accounting/GST traceability -- issued immediately only if `generate_invoice` is
    true, otherwise it stays a draft record. There used to be a bypass here that skipped invoice
    creation entirely whenever the calling admin's own organization_id happened to match the
    target entity's organization -- nothing prevents an admin-tier account from carrying a
    non-null organization_id, so that bypass let any admin who also owned/controlled a tenant
    organization credit its wallet with real, spendable balance and zero invoice/GST record. There
    is no legitimate case this endpoint needs to leave unrecorded -- if a truly invoice-less
    internal credit is ever needed, that should be its own explicit, separately-audited mechanism,
    not an incidental match on organization_id."""
    entity = db.get(Entity, payload.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    admin_user = None
    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
            admin_user = db.get(User, claims.get("sub"))
        except jwt.PyJWTError:
            admin_user = None

    primary_user = resolve_primary_user(db, entity.organization_id)
    try:
        rate_card = resolve_rate_card(db, primary_user) if primary_user else None
        if rate_card is None:
            raise DomainError("No default rate card is configured")
        credits, _slab = quote_credits(db, rate_card, payload.amount)
        wallet = credit_wallet(db, entity.id, credits, transaction_type="admin_credit", reference=payload.notes or "Admin manual credit")
    except DomainError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    invoice = create_draft_invoice(db, entity, type="admin_credit", base_amount=payload.amount, gst_amount=0.0, notes=payload.notes, created_by_admin_id=admin_user.id if admin_user else None)
    if payload.generate_invoice:
        issue_invoice(db, invoice)
    log_activity(db, entity.organization_id, "wallet_credited_by_admin", f"Admin credited Rs.{payload.amount:.2f} ({round(credits, 2)} credits) to entity '{entity.name}'.", actor_email=admin_user.email if admin_user else "admin (bootstrap key)", request=request)
    db.commit()

    available = float(wallet.prepaid_balance) + max(0, float(wallet.credit_limit) - float(wallet.credit_used))
    if invoice:
        db.refresh(invoice)
    return WalletCreditResponse(entity_id=entity.id, credits_added=round(credits, 2), available_balance=available, invoice=_invoice_out(invoice) if invoice else None)


def _razorpay_client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env.")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


@router.get("/payment-orders", response_model=list[PaymentOrderAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_payment_orders(order_status: str | None = None, db: Session = Depends(get_db)):
    query = select(PaymentOrder).order_by(PaymentOrder.created_at.desc())
    if order_status:
        query = query.where(PaymentOrder.status == order_status)
    orders = db.scalars(query).all()
    out = []
    for o in orders:
        entity = db.get(Entity, o.entity_id)
        org = db.get(Organization, entity.organization_id) if entity else None
        out.append(PaymentOrderAdminOut(
            id=o.id, entity_id=o.entity_id, entity_name=entity.name if entity else "(deleted entity)",
            organization_name=org.name if org else "(deleted organization)", provider=o.provider,
            provider_order_id=o.provider_order_id, amount=float(o.amount), purpose=o.purpose, status=o.status,
            created_at=o.created_at.isoformat(),
        ))
    return out


@router.post("/payment-orders/{order_id}/reconcile", response_model=PaymentOrderReconcileResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def reconcile_payment_order(order_id: str, db: Session = Depends(get_db)):
    """Cross-checks an order stuck at "created" (or "failed") against Razorpay's own record --
    the frontend only calls /verify after a successful checkout, so an abandoned or silently
    failed checkout leaves our row stale forever without this."""
    # Row-locked so two concurrent reconcile attempts (or a reconcile racing a /verify call)
    # serialize instead of both reading a not-yet-paid status and both crediting.
    order = db.get(PaymentOrder, order_id, with_for_update=True)
    if not order:
        raise HTTPException(status_code=404, detail="Payment order not found")
    client = _razorpay_client()
    before_status = order.status
    try:
        razorpay_order = client.order.fetch(order.provider_order_id)
        payments = client.order.payments(order.provider_order_id)
    except razorpay.errors.BadRequestError as exc:
        raise HTTPException(status_code=422, detail=f"Razorpay lookup failed: {exc}") from exc

    razorpay_status = razorpay_order.get("status", "unknown")
    captured = [p for p in payments.get("items", []) if p.get("status") == "captured"]
    action_taken = "no_change"

    if order.status != "paid" and captured:
        payment_id = captured[0]["id"]
        already_credited = db.scalar(select(WalletTransaction).where(WalletTransaction.reference == payment_id)) is not None
        if not already_credited:
            entity = db.get(Entity, order.entity_id)
            if order.purpose == "dlt_request" and order.reference_id:
                request_row = db.get(DltOnboardingRequest, order.reference_id)
                if request_row and request_row.status == "pending_payment":
                    _mark_dlt_request_paid(db, request_row, payment_id)
            else:
                credits = None
                if order.price_per_sms:
                    credits = float(order.amount) / float(order.price_per_sms)
                else:
                    primary_user = resolve_primary_user(db, entity.organization_id)
                    rate_card = resolve_rate_card(db, primary_user) if primary_user else None
                    if rate_card:
                        credits, _slab = quote_credits(db, rate_card, float(order.amount))
                if credits:
                    credit_wallet(db, entity.id, credits, transaction_type="recharge_razorpay_reconciled", reference=payment_id)
                    gst_amount = round(float(order.amount) * GST_RATE, 2)
                    invoice = create_draft_invoice(db, entity, type="wallet_recharge", base_amount=float(order.amount), gst_amount=gst_amount, reference=order.id)
                    issue_invoice(db, invoice)
        order.status = "paid"
        action_taken = "credited_and_marked_paid"
    elif order.status == "created" and not captured and razorpay_order.get("attempts", 0) > 0:
        # Razorpay shows checkout was attempted but nothing was ever captured -- treat as failed
        # rather than leaving it stuck at "created" forever.
        order.status = "failed"
        action_taken = "marked_failed"

    db.commit()
    return PaymentOrderReconcileResponse(our_status_before=before_status, razorpay_status=razorpay_status, action_taken=action_taken)


def _bulk_customer_stats(db: Session, organization_ids: list[str]):
    """Batches what would otherwise be ~4-5 separate queries per organization (entities, wallet
    per entity, message count, last-activity) into a handful of aggregate queries total,
    regardless of how many organizations exist -- used by both list_customers and
    get_usage_summary, whose per-org loops need identical stats."""
    entities_by_org: dict[str, list[Entity]] = {}
    if organization_ids:
        for e in db.scalars(select(Entity).where(Entity.organization_id.in_(organization_ids))).all():
            entities_by_org.setdefault(e.organization_id, []).append(e)
    all_entity_ids = [e.id for entities in entities_by_org.values() for e in entities]

    wallets_by_entity: dict[str, Wallet] = {}
    message_counts: dict[str, int] = {}
    last_activity: dict[str, object] = {}
    if all_entity_ids:
        for w in db.scalars(select(Wallet).where(Wallet.entity_id.in_(all_entity_ids))).all():
            wallets_by_entity[w.entity_id] = w
        for entity_id, count in db.execute(select(Message.entity_id, func.count()).where(Message.entity_id.in_(all_entity_ids)).group_by(Message.entity_id)).all():
            message_counts[entity_id] = count
        for entity_id, last_created in db.execute(select(Message.entity_id, func.max(Message.created_at)).where(Message.entity_id.in_(all_entity_ids)).group_by(Message.entity_id)).all():
            last_activity[entity_id] = last_created

    primary_by_org: dict[str, User] = {}
    if organization_ids:
        for u in db.scalars(select(User).where(User.organization_id.in_(organization_ids)).order_by(User.organization_id, User.created_at.asc())).all():
            primary_by_org.setdefault(u.organization_id, u)

    return entities_by_org, wallets_by_entity, message_counts, last_activity, primary_by_org


@router.post("/customers", response_model=AdminCreateCustomerResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_customer(payload: AdminCreateCustomerRequest, db: Session = Depends(get_db)):
    """Manually provisions a complete customer in one step -- organization, entity, both wallets,
    and a primary-contact login -- skipping self-registration and onboarding entirely (without
    this, the only way to get a customer into the system was to have them self-register, which
    always creates its own new organization; there's no way to attach a user to an org an admin
    pre-created via DLT Hierarchy's bare organization/entity forms).

    Unlike the old direct-create version of this endpoint, the admin never sets a password --
    the system generates one and the account starts in pending_verification, exactly like a
    self-registered account. The generated password and an email-verification code go out in one
    welcome email; from there the customer verifies email then mobile through the same
    /v1/auth/verify-email and /v1/auth/request-mobile-otp -> /v1/auth/verify-mobile steps
    self-registration uses, which is what flips status to active."""
    if db.scalar(select(User).where(User.email == payload.contact_email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    org = Organization(name=payload.organization_name, gstin=payload.gstin, pan=payload.pan, industry=payload.industry, address=payload.address)
    db.add(org)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An organization with this name already exists")

    entity = Entity(organization_id=org.id, name=payload.entity_name or payload.organization_name, status=StatusEnum.active)
    db.add(entity)
    db.flush()

    db.add(Wallet(entity_id=entity.id, prepaid_balance=0, credit_limit=0, credit_used=0))
    db.add(WabaWallet(entity_id=entity.id, prepaid_balance=0, credit_limit=0, credit_used=0))

    generated_password = secrets.token_urlsafe(9)
    user = User(
        email=payload.contact_email, password_hash=hash_password(generated_password), full_name=payload.contact_full_name,
        mobile=payload.contact_mobile, organization_id=org.id, role=UserRole.enterprise_customer.value,
        status=UserStatus.pending_verification, email_verified=False,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)

    email_code = _issue_otp(db, EmailVerification, user.id, channel="email", destination=user.email)
    verify_url = f"{settings.web_origin}/verify-account?user_id={user.id}"
    send_email(
        db,
        to=user.email,
        subject="Your Textzi account has been created",
        html_body=render_email(
            "Your Textzi account is ready",
            f"<p>Hi {user.full_name},</p><p>An admin created a Textzi account for you. Here's what you need to activate it:</p>"
            f"<table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"margin:16px 0; width:100%;\">"
            f"<tr><td style=\"padding:6px 0; color:#6a6a6a;\">Temporary password</td><td style=\"padding:6px 0; text-align:right;\"><b style=\"font-size:16px; letter-spacing:1px;\">{generated_password}</b></td></tr>"
            f"<tr><td style=\"padding:6px 0; color:#6a6a6a;\">Email verification code</td><td style=\"padding:6px 0; text-align:right;\"><b style=\"font-size:16px; letter-spacing:2px;\">{email_code}</b></td></tr>"
            f"</table>"
            f"<p>Click below, enter the code above to verify your email, then verify your mobile number to activate your account.</p>",
            cta_label="Activate Your Account",
            cta_url=verify_url,
        ),
    )

    return AdminCreateCustomerResponse(
        organization_id=org.id, entity_id=entity.id, user_id=user.id,
        dev_email_code=email_code if settings.environment == "development" else None,
        dev_generated_password=generated_password if settings.environment == "development" else None,
    )


@router.get("/customers", response_model=list[CustomerAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_customers(search: str | None = None, db: Session = Depends(get_db)):
    """Every organization shown with its primary contact's name -- the organization name alone
    (e.g. "Acme Retail Pvt Ltd") doesn't identify who the actual customer is, which made picking
    the right one in flows like admin wallet credit needlessly error-prone. Search matches the
    organization name or the primary contact's name/email.

    Excludes any organization with zero tenant-side users -- i.e. every user on it has a
    PLATFORM_INTERNAL_ROLES role (staff, not a customer). A real customer org always gets at
    least one tenant-role user at registration, so this is a reliable "not actually a customer"
    signal without hardcoding a name or id -- notably, it's what keeps the "Textzi Platform" org
    (home of the platform's own admin accounts, a holdover from before platform self-sending had
    its own dedicated tables) out of this list without touching that org/its users at all."""
    tenant_org_ids = {
        row[0] for row in db.execute(
            select(User.organization_id).where(User.organization_id.is_not(None), User.role.notin_(PLATFORM_INTERNAL_ROLES)).distinct()
        ).all()
    }
    orgs = [o for o in db.scalars(select(Organization).order_by(Organization.name)).all() if o.id in tenant_org_ids]
    entities_by_org, wallets_by_entity, message_counts, last_activity, primary_by_org = _bulk_customer_stats(db, [o.id for o in orgs])

    out = []
    search_lower = search.lower() if search else None
    for org in orgs:
        primary = primary_by_org.get(org.id)
        if search_lower:
            haystack = f"{org.name} {primary.full_name if primary else ''} {primary.email if primary else ''}".lower()
            if search_lower not in haystack:
                continue
        entities = entities_by_org.get(org.id, [])
        entity_ids = [e.id for e in entities]
        wallet_balance = sum(float(wallets_by_entity[eid].prepaid_balance) for eid in entity_ids if eid in wallets_by_entity)
        messages_sent = sum(message_counts.get(eid, 0) for eid in entity_ids)
        last_dt = max((last_activity[eid] for eid in entity_ids if eid in last_activity), default=None)
        out.append(CustomerAdminOut(
            organization_id=org.id, organization_name=org.name,
            primary_contact_name=primary.full_name if primary else None,
            primary_contact_email=primary.email if primary else None,
            primary_contact_mobile=primary.mobile if primary else None,
            entity_count=len(entities), wallet_balance=wallet_balance, messages_sent=messages_sent,
            last_activity=last_dt.isoformat() if last_dt else None,
        ))
    return out


@router.get("/usage/summary", response_model=UsageSummaryResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_usage_summary(db: Session = Depends(get_db)):
    orgs = db.scalars(select(Organization)).all()
    total_entities = db.scalar(select(func.count()).select_from(Entity)) or 0
    total_messages = db.scalar(select(func.count()).select_from(Message)) or 0
    total_credits_issued = db.scalar(select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(WalletTransaction.amount > 0)) or 0
    total_revenue = db.scalar(select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(Invoice.status == "issued")) or 0

    entities_by_org, wallets_by_entity, message_counts, last_activity, _primary_by_org = _bulk_customer_stats(db, [o.id for o in orgs])

    breakdown = []
    for org in orgs:
        entities = entities_by_org.get(org.id, [])
        entity_ids = [e.id for e in entities]
        messages_sent = sum(message_counts.get(eid, 0) for eid in entity_ids)
        wallet_balance = sum(float(wallets_by_entity[eid].prepaid_balance) for eid in entity_ids if eid in wallets_by_entity)
        last_dt = max((last_activity[eid] for eid in entity_ids if eid in last_activity), default=None)
        breakdown.append(UsageOrgBreakdown(
            organization_id=org.id, organization_name=org.name, entity_count=len(entities),
            messages_sent=messages_sent, wallet_balance=wallet_balance,
            last_activity=last_dt.isoformat() if last_dt else None,
        ))

    return UsageSummaryResponse(
        total_organizations=len(orgs), total_entities=total_entities, total_messages_sent=total_messages,
        total_wallet_credits_issued=float(total_credits_issued), total_revenue=float(total_revenue), breakdown=breakdown,
    )


AUDIT_LOG_LIMIT = 300
LOW_PLATFORM_WALLET_THRESHOLD = 100


@router.get("/audit-log", response_model=list[AdminAuditLogEntryOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_audit_log(actor_email: str | None = None, event_type: str | None = None, db: Session = Depends(get_db)):
    """Cross-organization view of AccountActivity -- the per-customer Reports > Activity Log
    (reports.py) only ever shows one org's own rows; this is the only place an admin can see
    everything, including org-less admin-only events (rate card changes, platform settings,
    staff logins) that never show up in any customer's own feed."""
    query = select(AccountActivity).order_by(AccountActivity.created_at.desc()).limit(AUDIT_LOG_LIMIT)
    if actor_email:
        query = query.where(AccountActivity.actor_email.ilike(f"%{actor_email}%"))
    if event_type:
        query = query.where(AccountActivity.event_type == event_type)
    rows = db.scalars(query).all()
    org_ids = {r.organization_id for r in rows if r.organization_id}
    org_names = {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all()} if org_ids else {}
    return [
        AdminAuditLogEntryOut(
            id=r.id, event_type=r.event_type, description=r.description, actor_email=r.actor_email,
            ip_address=r.ip_address, user_agent=r.user_agent, organization_name=org_names.get(r.organization_id), created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


MESSAGE_LOG_LIMIT = 200


@router.get("/messages", response_model=list[AdminMessageOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_admin_messages(entity_id: str | None = None, status_filter: str | None = None, limit: int = MESSAGE_LOG_LIMIT, offset: int = 0, db: Session = Depends(get_db)):
    """Cross-organization view of tenant Message rows -- "other user"'s SMS log/report, filterable
    down to one customer. Masking follows each message's own is_encrypted flag, exactly like the
    customer's own Logs tab (sms.py's list_my_messages) -- an admin never sees more than the
    customer themselves chose to expose."""
    limit = max(1, min(limit, MESSAGE_LOG_LIMIT))
    offset = max(0, offset)
    query = select(Message).order_by(Message.created_at.desc()).limit(limit).offset(offset)
    if entity_id:
        query = query.where(Message.entity_id == entity_id)
    if status_filter:
        query = query.where(Message.status == status_filter)
    messages = db.scalars(query).all()

    entity_ids = {m.entity_id for m in messages}
    entities = {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(entity_ids))).all()} if entity_ids else {}
    org_ids = {e.organization_id for e in entities.values()}
    org_names = {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all()} if org_ids else {}

    message_ids = [m.id for m in messages]
    latest_attempt: dict[str, DeliveryAttempt] = {}
    if message_ids:
        for a in db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.message_id.in_(message_ids)).order_by(DeliveryAttempt.created_at.desc())).all():
            latest_attempt.setdefault(a.message_id, a)  # first seen per id, in desc order, is the latest

    result = []
    for m in messages:
        entity = entities.get(m.entity_id)
        attempt = latest_attempt.get(m.id)
        result.append(AdminMessageOut(
            id=m.id,
            organization_name=org_names.get(entity.organization_id) if entity else None,
            entity_name=entity.name if entity else m.entity_id,
            recipient=mask_mobile(decrypt_recipient_lenient(m.recipient)) if m.is_encrypted else m.recipient,
            rendered_body="[Encrypted]" if m.is_encrypted else m.rendered_body,
            status=m.status,
            route=m.route,
            credits_charged=m.credits_charged,
            delivery_status_code=attempt.delivery_status_code if attempt else None,
            delivery_error=attempt.error if attempt else None,
            created_at=m.created_at.isoformat(),
        ))
    return result


@router.get("/platform-messages", response_model=list[AdminPlatformMessageOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_admin_platform_messages(limit: int = MESSAGE_LOG_LIMIT, offset: int = 0, db: Session = Depends(get_db)):
    """The platform's own SMS log ("self", as opposed to /messages' "other user") -- currently
    just login-OTP sends. Entirely separate from tenant Message rows; see PlatformMessage."""
    limit = max(1, min(limit, MESSAGE_LOG_LIMIT))
    offset = max(0, offset)
    messages = db.scalars(select(PlatformMessage).order_by(PlatformMessage.created_at.desc()).limit(limit).offset(offset)).all()
    return [
        AdminPlatformMessageOut(
            id=m.id, purpose=m.purpose, recipient=mask_mobile(m.recipient),
            rendered_body=redact_otp(m.rendered_body), status=m.status, route=m.route,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]


@router.get("/contact-messages", response_model=list[ContactMessageAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_contact_messages(limit: int = MESSAGE_LOG_LIMIT, offset: int = 0, db: Session = Depends(get_db)):
    """Submissions from the public marketing site's Contact form (public.py's submit_contact) --
    persisted independent of whether the internal notification email actually sent, so nothing
    submitted here is ever silently lost even if SMTP is misconfigured."""
    limit = max(1, min(limit, MESSAGE_LOG_LIMIT))
    offset = max(0, offset)
    rows = db.scalars(select(ContactMessage).order_by(ContactMessage.created_at.desc()).limit(limit).offset(offset)).all()
    return [
        ContactMessageAdminOut(
            id=r.id, name=r.name, email=r.email, phone=r.phone, company=r.company,
            message=r.message, email_sent=r.email_sent, created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/testimonials", response_model=list[TestimonialAdminOut], dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_testimonials(status_filter: str | None = None, db: Session = Depends(get_db)):
    """Every testimonial -- customer-submitted (pending review) and admin-authored (already
    approved) alike. Filter by status_filter=pending to get exactly the moderation queue."""
    query = select(Testimonial).order_by(Testimonial.created_at.desc())
    if status_filter:
        query = query.where(Testimonial.status == status_filter)
    rows = db.scalars(query).all()

    org_ids = {r.organization_id for r in rows if r.organization_id}
    org_names = {}
    if org_ids:
        for org in db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all():
            org_names[org.id] = org.name
    user_ids = {r.submitted_by_user_id for r in rows if r.submitted_by_user_id}
    user_emails = {}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            user_emails[u.id] = u.email

    return [
        TestimonialAdminOut(
            id=r.id, organization_name=org_names.get(r.organization_id) if r.organization_id else None,
            submitted_by_email=user_emails.get(r.submitted_by_user_id) if r.submitted_by_user_id else None,
            author_name=r.author_name, author_role=r.author_role, quote=r.quote, status=r.status,
            created_at=r.created_at.isoformat(), reviewed_at=r.reviewed_at.isoformat() if r.reviewed_at else None,
            reviewed_by=r.reviewed_by,
        )
        for r in rows
    ]


@router.post("/testimonials", response_model=TestimonialAdminOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_testimonial(payload: TestimonialAdminCreateRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Admin-authored testimonial -- e.g. a quote a customer emailed in rather than submitted
    through the form. Live/public immediately, no separate approval step needed since an admin
    is the one entering it."""
    row = Testimonial(
        author_name=payload.author_name, author_role=payload.author_role, quote=payload.quote,
        status="approved", reviewed_at=datetime.now(timezone.utc), reviewed_by=_caller_email(authorization, db),
    )
    db.add(row)
    log_activity(db, None, "testimonial_created_by_admin", f"Admin added a testimonial from '{payload.author_name}'.", actor_email=_caller_email(authorization, db), request=request)
    db.commit()
    db.refresh(row)
    return TestimonialAdminOut(
        id=row.id, organization_name=None, submitted_by_email=None, author_name=row.author_name,
        author_role=row.author_role, quote=row.quote, status=row.status, created_at=row.created_at.isoformat(),
        reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None, reviewed_by=row.reviewed_by,
    )


@router.patch("/testimonials/{testimonial_id}/status", response_model=TestimonialAdminOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def update_testimonial_status(testimonial_id: str, payload: TestimonialStatusUpdateRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    row = db.get(Testimonial, testimonial_id)
    if not row:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    row.status = payload.status
    row.reviewed_at = datetime.now(timezone.utc)
    row.reviewed_by = _caller_email(authorization, db)
    log_activity(db, row.organization_id, f"testimonial_{payload.status}", f"Testimonial from '{row.author_name}' {payload.status} by admin.", actor_email=row.reviewed_by, request=request)
    db.commit()
    db.refresh(row)

    org_name = None
    if row.organization_id:
        org = db.get(Organization, row.organization_id)
        org_name = org.name if org else None
    submitted_by_email = None
    if row.submitted_by_user_id:
        u = db.get(User, row.submitted_by_user_id)
        submitted_by_email = u.email if u else None

    return TestimonialAdminOut(
        id=row.id, organization_name=org_name, submitted_by_email=submitted_by_email,
        author_name=row.author_name, author_role=row.author_role, quote=row.quote, status=row.status,
        created_at=row.created_at.isoformat(), reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        reviewed_by=row.reviewed_by,
    )


@router.delete("/testimonials/{testimonial_id}", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def delete_testimonial(testimonial_id: str, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    row = db.get(Testimonial, testimonial_id)
    if not row:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    log_activity(db, row.organization_id, "testimonial_deleted", f"Testimonial from '{row.author_name}' deleted by admin.", actor_email=_caller_email(authorization, db), request=request)
    db.delete(row)
    db.commit()
    return {"id": testimonial_id, "deleted": True}


@router.get("/messages/{message_id}/telemetry", response_model=MessageTelemetryOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_message_telemetry(message_id: str, db: Session = Depends(get_db)):
    """Full request/response chain for one customer send -- the inbound API request and our
    response, plus every route attempt's outbound request, provider response, and (once one
    arrives) the raw DR webhook payload. Everything returned here was already scrubbed of
    plaintext recipient/message content at write time if the message is_encrypted (see
    dispatch.py/webhooks.py) -- this endpoint doesn't need to mask it again, except for the
    Message row's own top-level recipient/rendered_body fields, which follow the same
    is_encrypted convention as list_admin_messages."""
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    attempts = db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.message_id == message_id).order_by(DeliveryAttempt.created_at)).all()
    return MessageTelemetryOut(
        message_id=message.id,
        recipient=mask_mobile(decrypt_recipient_lenient(message.recipient)) if message.is_encrypted else message.recipient,
        rendered_body="[Encrypted]" if message.is_encrypted else message.rendered_body,
        status=message.status,
        request_payload=message.request_payload,
        response_payload=message.response_payload,
        created_at=message.created_at.isoformat(),
        attempts=[
            DeliveryAttemptTelemetryOut(
                id=a.id, route=a.route, status=a.status, provider_message_id=a.provider_message_id, error=a.error,
                delivery_status_code=a.delivery_status_code, delivered_at=a.delivered_at.isoformat() if a.delivered_at else None,
                request_payload=a.request_payload, response_body=a.response_body, webhook_payload=a.webhook_payload,
                created_at=a.created_at.isoformat(),
            )
            for a in attempts
        ],
    )


@router.get("/platform-messages/{message_id}/telemetry", response_model=PlatformMessageTelemetryOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_platform_message_telemetry(message_id: str, db: Session = Depends(get_db)):
    """Same drill-down as get_message_telemetry, for the platform's own sends. request_payload
    already has the OTP code redacted at write time (see auth.py's _send_platform_otp_sms) -- the
    rendered_body field returned here goes through the same redact_otp() as the list endpoint."""
    message = db.get(PlatformMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Platform message not found")
    return PlatformMessageTelemetryOut(
        message_id=message.id, purpose=message.purpose, recipient=mask_mobile(message.recipient),
        rendered_body=redact_otp(message.rendered_body), status=message.status, route=message.route,
        request_payload=message.request_payload, response_body=message.response_body,
        created_at=message.created_at.isoformat(),
    )


@router.get("/notifications", response_model=list[NotificationOut], dependencies=[Depends(require_admin)])
def get_admin_notifications(db: Session = Depends(get_db)):
    """Real signals instead of the nav bar's previously-hardcoded demo data: pending DLT requests
    needing review, a low platform wallet balance (which silently degrades login-OTP sending --
    see auth.py's _send_platform_otp_sms, which fails open with no other visibility into this),
    and payment orders stuck in 'created' (never completed, never explicitly failed)."""
    notifications: list[NotificationOut] = []

    pending_dlt = db.scalar(select(func.count()).select_from(DltOnboardingRequest).where(DltOnboardingRequest.status == "pending_payment")) or 0
    if pending_dlt:
        notifications.append(NotificationOut(
            id="dlt-pending", severity="info", title=f"{pending_dlt} DLT request{'s' if pending_dlt != 1 else ''} awaiting review",
            description="Pending DLT onboarding requests need a status update.", link="/dlt-requests",
        ))

    platform_wallet = db.get(PlatformWallet, "platform")
    if platform_wallet and float(platform_wallet.balance) < LOW_PLATFORM_WALLET_THRESHOLD:
        notifications.append(NotificationOut(
            id="platform-wallet-low", severity="warning", title="Platform wallet balance is low",
            description=f"Only {float(platform_wallet.balance):.0f} credits left -- login OTP SMS will silently stop sending once this hits zero.", link="/platform-wallet",
        ))

    stuck_payments = db.scalar(select(func.count()).select_from(PaymentOrder).where(PaymentOrder.status == "created")) or 0
    if stuck_payments:
        notifications.append(NotificationOut(
            id="payments-stuck", severity="warning", title=f"{stuck_payments} payment order{'s' if stuck_payments != 1 else ''} never completed",
            description="These Razorpay orders were created but never verified as paid or failed -- check Payment Reconciliation.", link="/payment-reconciliation",
        ))

    return notifications


@router.get("/organizations/{organization_id}/overview", response_model=OrganizationOverviewResponse, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_organization_overview(organization_id: str, db: Session = Depends(get_db)):
    """The complete admin-side view of one customer: org details, every entity with its full DLT
    hierarchy (PE IDs -> headers, plus templates), team, invoices, recharge ledger, and raw
    payment-gateway orders. Customer-facing accounts never see this endpoint (require_admin);
    their own equivalent views (Wallet/Payment/Purchase Ledger under Reports) are separately
    scoped to just their own entity, not this full cross-entity admin picture."""
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    entities = db.scalars(select(Entity).where(Entity.organization_id == org.id)).all()
    entity_ids = [e.id for e in entities]
    messages_sent = (db.scalar(select(func.count()).select_from(Message).where(Message.entity_id.in_(entity_ids))) or 0) if entity_ids else 0
    wallet_balance = sum(float(w.prepaid_balance) for e in entities if (w := db.get(Wallet, e.id)))
    total_recharged = (db.scalar(select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
        WalletTransaction.entity_id.in_(entity_ids), WalletTransaction.type.in_(["recharge", "recharge_razorpay", "recharge_razorpay_reconciled"]),
    )) or 0) if entity_ids else 0
    users = db.scalars(select(User).where(User.organization_id == org.id).order_by(User.created_at.asc())).all()
    primary = users[0] if users else None
    primary_2fa = db.get(TwoFactorAuth, primary.id) if primary else None
    invoices = db.scalars(select(Invoice).where(Invoice.entity_id.in_(entity_ids)).order_by(Invoice.created_at.desc())).all() if entity_ids else []

    entity_details: list[EntityAdminDetailOut] = []
    recharges: list[RechargeDetailOut] = []
    payments: list[PaymentDetailOut] = []
    if entity_ids:
        pes_by_entity: dict[str, list[PeId]] = {}
        for pe in db.scalars(select(PeId).where(PeId.entity_id.in_(entity_ids))).all():
            pes_by_entity.setdefault(pe.entity_id, []).append(pe)
        all_pe_ids = [pe.id for pes in pes_by_entity.values() for pe in pes]
        headers_by_pe: dict[str, list[HeaderModel]] = {}
        if all_pe_ids:
            for h in db.scalars(select(HeaderModel).where(HeaderModel.pe_id.in_(all_pe_ids))).all():
                headers_by_pe.setdefault(h.pe_id, []).append(h)
        templates_by_entity: dict[str, list[Template]] = {}
        for t in db.scalars(select(Template).where(Template.entity_id.in_(entity_ids))).all():
            templates_by_entity.setdefault(t.entity_id, []).append(t)

        for e in entities:
            entity_details.append(EntityAdminDetailOut(
                id=e.id, name=e.name, status=e.status,
                pe_ids=[
                    PeIdAdminOut(
                        id=pe.id, value=pe.value, operator=pe.operator, status=pe.status,
                        headers=[HeaderAdminOut(id=h.id, header_id=h.header_id, value=h.value, status=h.status) for h in headers_by_pe.get(pe.id, [])],
                    )
                    for pe in pes_by_entity.get(e.id, [])
                ],
                templates=[TemplateAdminDetailOut(id=t.id, alias=t.alias, dlt_template_id=t.dlt_template_id, category=t.category, status=t.status) for t in templates_by_entity.get(e.id, [])],
            ))

        recharge_rows = db.scalars(
            select(WalletTransaction).where(WalletTransaction.entity_id.in_(entity_ids), WalletTransaction.type.in_(["recharge", "recharge_razorpay", "recharge_razorpay_reconciled"])).order_by(WalletTransaction.created_at.desc()),
        ).all()
        recharges = [RechargeDetailOut(id=r.id, type=r.type, amount=float(r.amount), reference=r.reference, created_at=r.created_at.isoformat()) for r in recharge_rows]

        payment_rows = db.scalars(select(PaymentOrder).where(PaymentOrder.entity_id.in_(entity_ids)).order_by(PaymentOrder.created_at.desc())).all()
        payments = [PaymentDetailOut(id=p.id, provider=p.provider, provider_order_id=p.provider_order_id, amount=float(p.amount), status=p.status, created_at=p.created_at.isoformat()) for p in payment_rows]

    return OrganizationOverviewResponse(
        organization_id=org.id, organization_name=org.name, gstin=org.gstin, pan=org.pan, industry=org.industry,
        address=org.address, created_at=org.created_at.isoformat(), entities=entity_details,
        wallet_balance=wallet_balance, messages_sent=messages_sent, total_recharged=float(total_recharged),
        primary_contact_name=primary.full_name if primary else None,
        primary_contact_email=primary.email if primary else None,
        primary_contact_mobile=primary.mobile if primary else None,
        primary_contact_two_factor_enabled=bool(primary_2fa and primary_2fa.enabled),
        users=[TeamMemberOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, status=u.status) for u in users],
        invoices=[_invoice_out(i) for i in invoices],
        recharges=recharges,
        payments=payments,
    )
