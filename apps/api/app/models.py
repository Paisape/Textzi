import enum
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


class Status(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    pending = "pending"


class UserStatus(str, enum.Enum):
    pending_verification = "pending_verification"
    active = "active"
    suspended = "suspended"


class UserRole(str, enum.Enum):
    """PRD §5 role list. Stored as a plain string column (not a native Postgres enum type) so new
    roles can be added without a migration -- validated at the API boundary via this enum instead."""
    super_admin = "super_admin"
    operator_admin = "operator_admin"
    finance_team = "finance_team"
    support_team = "support_team"
    sales_team = "sales_team"
    reseller = "reseller"
    agency = "agency"
    enterprise_customer = "enterprise_customer"
    developer = "developer"
    sub_user = "sub_user"
    finance_user = "finance_user"
    marketing_user = "marketing_user"
    read_only_user = "read_only_user"


ADMIN_ROLES = {UserRole.super_admin.value, UserRole.operator_admin.value}

# Platform staff, as opposed to tenant/customer-side accounts (enterprise_customer, sub_user,
# finance_user, marketing_user, read_only_user) -- the Admin "Users" page lists only these; every
# customer-side account is managed instead through the "Customers" section.
PLATFORM_INTERNAL_ROLES = {
    UserRole.super_admin.value, UserRole.operator_admin.value, UserRole.finance_team.value,
    UserRole.support_team.value, UserRole.sales_team.value, UserRole.reseller.value,
    UserRole.agency.value, UserRole.developer.value,
}


class MessageCategory(str, enum.Enum):
    """TRAI-recognised DLT message categories. Each carries its own per-message rate in
    RateSlab -- transactional/OTP costs more than bulk promotional, matching how Indian SMS
    billing actually works instead of one flat per-message price."""
    transactional = "transactional"
    otp = "otp"
    service_implicit = "service_implicit"
    service_explicit = "service_explicit"
    promotional = "promotional"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mobile_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160))
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.pending_verification)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.enterprise_customer.value)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    login_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # WhatsApp inbox agent-capacity cap -- null means unlimited. Checked when assigning a
    # conversation to this user (see waba_inbox.assign_conversation); not a hard cross-org
    # constraint, just this one number an admin/teammate can set per agent.
    max_open_conversations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # CRM team hierarchy -- who this person's manager is, within the same organization. Used for
    # sales-target roll-ups and as a future approval-chain target; deliberately just one level
    # (not a full org chart), matching the SME-appropriate scope decided for this CRM build.
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # null = full access to whatever channels the org has active (default, matches every account
    # created before this field existed). "sms" | "waba" | "crm" restricts a teammate to only
    # that channel's focused workspace -- set at invite time, never self-service editable.
    channel_scope: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # null = every page within channel_scope (today's behavior). A list of frontend route names
    # (e.g. ["crm-leads", "crm-contacts"]) narrows further -- only meaningful alongside a single
    # channel_scope, set at invite time. Enforced both ways: the frontend nav/router guard hides
    # and blocks navigation to unscoped pages, and permissions.require_page_scope/
    # require_page_scope_for reject the matching backend endpoints directly, so a restricted
    # teammate can't bypass the UI by calling the API.
    page_scope: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TwoFactorAuth(Base):
    """TOTP secret for one user. A row with `enabled=False` is a pending, not-yet-confirmed
    enrollment (the user scanned/entered the secret but hasn't proven possession yet).
    `secret_encrypted` uses the same Fernet encryption already used for provider secrets --
    never stored in plaintext."""
    __tablename__ = "two_factor_auth"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    secret_encrypted: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The 30-second time-step counter of the last successfully-verified code (see
    # security.verify_totp) -- closes the replay window a still-valid TOTP code would otherwise
    # have for a second sensitive action within the same ~90-second window.
    last_used_step: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TwoFactorRecoveryCode(Base):
    """One row per single-use TOTP recovery/backup code -- a batch of 10 is generated once when
    2FA is confirmed (two_factor.py's confirm()), shown to the user exactly once in that response,
    never retrievable again afterward (only code_hash is persisted). Usable in place of a live TOTP
    code at login (auth.py's login_verify_2fa), step-up (step_up_2fa), or self-service disable, so
    losing the authenticator device doesn't strand a user with admin force-disable as the only way
    back in. code_hash uses the same HMAC-SHA256 scheme as OTPs (security.hash_otp) -- these codes
    have far higher entropy than a 6-digit OTP, but no reason not to reuse a proven scheme."""
    __tablename__ = "two_factor_recovery_codes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MobileVerification(Base):
    __tablename__ = "mobile_verifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mobile: Mapped[str] = mapped_column(String(20))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKeyActionOtp(Base):
    """One-time codes gating sensitive Channels > SMS > API Keys actions -- generating a new key
    (the plaintext is shown exactly once, per hash_api_key's one-way storage, so this is the only
    checkpoint before it's revealed) and changing an existing key's IP allow-list. Delivered to
    the account's verified mobile if it has one (via the platform's own OTP SMS sending),
    otherwise email. One shared table for both actions -- `action` disambiguates which one a
    pending code was issued for, so requesting a code for one never authorizes the other."""
    __tablename__ = "api_key_action_otps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordReset(Base):
    """Self-service password reset -- deliberately only ever issued for customer-side roles
    (see auth.py's forgot_password); a platform-staff account's password can only be reset by
    another admin (POST /v1/admin/users/{id}/reset-password), never through this public,
    email-enumerable endpoint."""
    __tablename__ = "password_resets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    """One row per issued access token that logged a user in (login, 2FA-verified login, invite
    acceptance) -- its id is embedded in the token as the `sid` claim, and require_user rejects
    any token whose session has been revoked. Lets a user see and individually kill other active
    logins from Account Security, and is the actual mechanism behind that page's session list."""
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Primary business contact for this organization -- distinct from the login account that
    # completed onboarding (AdminCreateCustomerRequest's admin-provisioning path already has its
    # own contact_* fields, but those become the User row itself; here the user already exists,
    # so these are just organization-level fields). Nullable at the DB layer so
    # AdminCreateCustomerRequest's org-creation path (which doesn't collect these) keeps working
    # unchanged -- required-ness for self-service onboarding is enforced in OrganizationOnboardRequest.
    contact_person_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Zoho Books Contact id -- null until an admin explicitly links this organization (admin.py's
    # POST .../zoho-sync, zoho_books._ensure_customer), never created automatically. Every later
    # invoice reuses it instead of creating a duplicate Contact.
    zoho_contact_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    # 2-letter GST jurisdiction state code, only ever used when this org has no GSTIN (otherwise
    # the GSTIN's own prefix is authoritative -- see services.state_code_from_gstin). Captured via
    # the State dropdown on onboarding/complete-profile, needed to resolve interstate (IGST) vs
    # intrastate (CGST+SGST) at Zoho invoice sync time.
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # Proof of GST registration, uploaded the first time the company profile is completed --
    # mirrors PeId.certificate_path's storage convention (services.save_upload).
    gst_certificate_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Null until the mandatory post-first-login "Complete Your Profile" gate (router guard,
    # apps/web/src/plugins/1.router/index.ts) has been submitted once -- every existing
    # organization starts null too, so this doubles as the retroactive gate for accounts that
    # onboarded before this field existed, not just brand new ones.
    profile_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.pending)


class PeId(Base):
    __tablename__ = "pe_ids"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    value: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(80))
    certificate_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Proof the customer submitted a PE-TM chain mapping request from their own DLT operator
    # login, selecting Textzi as their Telemarketer -- only meaningful for self-service (a
    # customer bringing their own already-registered PE has to link it to Textzi themselves);
    # the full-service DltOnboardingRequest flow doesn't need this since Textzi's own team
    # handles the mapping directly as part of doing the whole registration.
    pe_tm_mapping_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.pending)
    __table_args__ = (UniqueConstraint("entity_id", "value", name="uq_entity_pe"),)


class Header(Base):
    __tablename__ = "headers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pe_id: Mapped[str] = mapped_column(ForeignKey("pe_ids.id"), index=True)
    header_id: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(32))
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.pending)
    __table_args__ = (UniqueConstraint("pe_id", "header_id", name="uq_pe_header"),)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    pe_id: Mapped[str] = mapped_column(ForeignKey("pe_ids.id"))
    header_id: Mapped[str] = mapped_column(ForeignKey("headers.id"))
    alias: Mapped[str] = mapped_column(String(80))
    dlt_template_id: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20), default=MessageCategory.transactional.value)
    status: Mapped[Status] = mapped_column(Enum(Status), default=Status.pending)
    __table_args__ = (
        UniqueConstraint("entity_id", "alias", name="uq_entity_template_alias"),
        UniqueConstraint("entity_id", "dlt_template_id", name="uq_entity_dlt_template_id"),
    )


class RateCard(Base):
    """A named pricing plan. `channel` ("sms" or "whatsapp") is purely a label for grouping and
    public-pricing display -- only "sms" channel cards are ever consulted for real billing
    (resolve_rate_card/quote_credits/wallet recharge); a "whatsapp" card exists so admins can
    publish WhatsApp pricing on the public site even though WABA billing itself is still flat
    recharge, not slab-priced. Exactly one "sms" card is `is_default` at a time -- that's the
    card every user gets unless a UserRateCard row assigns them a different one. Category no
    longer affects price ("our rate is same for all type of sms") -- a card's RateCardSlabs
    price purely by the rupee amount of the recharge itself.
    `show_on_public_pricing` + `public_tagline` control whether/how this card appears on the
    public marketing site's Pricing section -- admin-controlled, off by default."""
    __tablename__ = "rate_cards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    channel: Mapped[str] = mapped_column(String(12), default="sms")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    min_recharge_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=500)
    show_on_public_pricing: Mapped[bool] = mapped_column(Boolean, default=False)
    public_tagline: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateCardSlab(Base):
    """One rupee-amount bracket of a RateCard, e.g. a recharge of Rs.1-1000 buys credits at
    Rs.0.25/SMS, Rs.1001-3000 at Rs.0.23/SMS. `max_amount` NULL means this is the
    top/unbounded bracket. The bracket is matched against the recharge amount itself, not the
    quantity of SMS it buys."""
    __tablename__ = "rate_card_slabs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rate_card_id: Mapped[str] = mapped_column(ForeignKey("rate_cards.id"), index=True)
    min_amount: Mapped[float] = mapped_column(Numeric(12, 2))
    max_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_per_sms: Mapped[float] = mapped_column(Numeric(10, 4))


class UserRateCard(Base):
    """Assigns one specific user to a non-default RateCard. Absence of a row here means the
    user gets whichever card has is_default=True."""
    __tablename__ = "user_rate_cards"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    rate_card_id: Mapped[str] = mapped_column(ForeignKey("rate_cards.id"), index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_ips: Mapped[list] = mapped_column(JSON, default=list)  # empty list = no IP restriction


class Wallet(Base):
    """The SMS-channel wallet. See WabaWallet for the separate WhatsApp-channel balance --
    kept as two distinct tables (rather than one wallet with a channel column) so this table's
    existing primary key and every call site built around entity_id doesn't need to change."""
    __tablename__ = "wallets"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    prepaid_balance: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    credit_limit: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    credit_used: Mapped[float] = mapped_column(Numeric(14, 4), default=0)


class WabaWallet(Base):
    """The WhatsApp-channel wallet -- same shape as Wallet, kept as its own table so SMS and
    WABA balances never share a row or a query path."""
    __tablename__ = "waba_wallets"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    prepaid_balance: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    credit_limit: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    credit_used: Mapped[float] = mapped_column(Numeric(14, 4), default=0)


class TextziWallet(Base):
    """A separate rupee-balance wallet, distinct from Wallet/WabaWallet's SMS-/WhatsApp-credit
    balances -- funded only by Razorpay Smart Collect bank transfers (net of the platform's flat
    fee, see PlatformPaymentMethodConfig), spendable across SMS credit top-up, WABA subscription,
    and CRM subscription purchase. Prepaid-only, no credit_limit/credit_used -- unlike Wallet/
    WabaWallet there's no credit-line concept here, just a plain balance."""
    __tablename__ = "textzi_wallets"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    balance: Mapped[float] = mapped_column(Numeric(14, 4), default=0)


class TextziWalletTransaction(Base):
    """Audit ledger for TextziWallet, same shape/purpose as WalletTransaction -- one row per
    credit (Smart Collect top-up) or debit (spend on SMS/WABA/CRM). type is a free string
    following this codebase's existing convention (WalletTransaction has no enum either):
    "smart_collect_topup" | "spend_sms_credit" | "spend_waba_subscription" |
    "spend_crm_subscription". reference is the Razorpay payment id (credits) or the resulting
    Message/ChannelSubscription id (debits) -- used by the Smart Collect webhook handler to
    detect and skip an already-processed retry."""
    __tablename__ = "textzi_wallet_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Numeric(14, 4))
    balance_after: Mapped[float] = mapped_column(Numeric(14, 4))
    reference: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RazorpayVirtualAccount(Base):
    """One row per entity that has generated Smart Collect bank-transfer details -- entity_id as
    primary key mirrors WabaConnection's own convention (at most one live virtual account per
    entity). razorpay_account_id is what an incoming virtual_account.credited webhook carries,
    used to map the credit back to this entity."""
    __tablename__ = "razorpay_virtual_accounts"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    razorpay_account_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vpa: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="active")  # "active" | "closed"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformPaymentMethodConfig(Base):
    """Admin-editable, per-method kill switch for wallet/subscription payment -- same enabled-flag
    shape and purpose as ChannelFeeConfig.enabled (checked before either Razorpay Checkout or
    Smart Collect is offered anywhere, frontend or backend). flat_fee_paise only applies to
    "razorpay_smart_collect" -- deducted from every bank transfer before crediting TextziWallet,
    admin-configurable rather than hardcoded since it's meant to track Razorpay's own real cost
    (or a margin on top), not a fixed product constant."""
    __tablename__ = "platform_payment_method_configs"
    payment_method: Mapped[str] = mapped_column(String(30), primary_key=True)  # "razorpay_checkout" | "razorpay_smart_collect"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    flat_fee_paise: Mapped[int] = mapped_column(Integer, default=0)


class PlatformWabaSettings(Base):
    """Singleton row. Textzi's own Meta Tech Provider app credentials for WhatsApp Embedded
    Signup -- editable from the admin UI, not just `.env`, same convention as
    PlatformTurnstileSettings/PlatformSmtpSettings/PlatformR2Settings above. app_id/config_id
    aren't secrets (app_id ships to every customer's browser via the Facebook JS SDK regardless;
    config_id is scoped to a specific embedded-signup configuration, not a credential) so they're
    stored/returned plain; app_secret is write-only (encrypted at rest, never returned by GET) --
    it's what lets anyone exchange a signup code for a real access token."""
    __tablename__ = "platform_waba_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    app_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_secret_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The value Meta's own webhook GET handshake echoes back (hub.verify_token) -- chosen by us,
    # pasted into Meta's App Dashboard webhook config, same "generate once, re-showable on
    # demand" convention as TTBS's webhook_secret (provider_routes.py) since the worst case of a
    # leak is low (it only lets someone complete the harmless GET handshake -- the real trust
    # boundary for actual message events is the X-Hub-Signature-256/app-secret check).
    webhook_verify_token_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)


class WabaConnection(Base):
    """One row per entity that has connected a WhatsApp Business Account via Embedded Signup --
    entity_id as the primary key mirrors TwoFactorAuth's user_id-as-PK convention (at most one
    live connection per entity at a time; reconnecting overwrites it rather than accumulating
    history rows, same reasoning as TwoFactorAuth re-enrollment). access_token is the long-lived
    token Meta issues for this WABA, Fernet-encrypted like every other third-party credential in
    this codebase (security.encrypt_secret) -- it's what actually lets Textzi send/receive on the
    customer's behalf, so it's exactly as sensitive as the TTBS account password or a provider
    route's auth token."""
    __tablename__ = "waba_connections"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    waba_id: Mapped[str] = mapped_column(String(64))
    phone_number_id: Mapped[str] = mapped_column(String(64))
    business_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    verified_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    # Meta's /register endpoint ties a phone number to a two-step-verification PIN on first
    # registration; later /register calls for the SAME number are expected to supply the SAME
    # PIN, not a fresh one -- persisted (Fernet-encrypted, like the access token) so a retry or a
    # reconnect of the same number reuses it instead of registration silently failing every time
    # after the first.
    registration_pin_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="connected")
    # Refreshed on-demand (not fetched on every page load -- these come from a real Meta call, no
    # need to spend it that often) via POST .../refresh-status. GREEN/YELLOW/RED/UNKNOWN/NA per
    # Meta's own quality_rating field; messaging_tier is the current 24h unique-conversation cap
    # (TIER_250/TIER_2K/TIER_10K/TIER_100K/UNLIMITED, from the throughput field).
    quality_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    messaging_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Meta Commerce Manager catalog id -- created and populated (products/prices/images) entirely
    # in Meta's own tools, not by Textzi; this is just the reference a catalog/product message's
    # `action.catalog_id` needs. Optional/self-service (a plain text field the customer pastes
    # in), not fetched or validated via a Graph API call at save time.
    catalog_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WabaCatalogItem(Base):
    """A read-only local mirror of one product in the entity's Meta Commerce Manager catalog --
    synced periodically (catalog_sync.py) so the agent inbox can show a searchable product picker
    instead of requiring an agent to already know a product's retailer_id by heart. Meta's catalog
    stays the source of truth for price/availability/existence; this table is a display cache, not
    something Textzi writes back to Meta. Deleting a product in Meta just means it stops
    reappearing on the next sync -- stale rows aren't proactively pruned mid-sync since an
    in-flight order (waba_orders) may still reference a retailer_id whose catalog row disappeared,
    and that lookup should degrade gracefully, not break."""
    __tablename__ = "waba_catalog_items"
    __table_args__ = (UniqueConstraint("entity_id", "product_retailer_id", name="uq_waba_catalog_items_entity_retailer_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    product_retailer_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    price: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WabaOrder(Base):
    """A structured record of a WhatsApp native-cart order (Meta's `type: "order"` inbound
    webhook message -- customer taps through a catalog/product message, adds items, taps "Review
    and send" inside WhatsApp itself). The chat bubble showing the order already exists
    (ConversationMessage with message_type="order", raw payload in .payload) -- this is additive,
    not a replacement: a real status lifecycle an agent can actually act on, since Meta's own
    order-status push-back message only exists inside its separate, gated Payments API flow (see
    Addendum 14's own research notes), not for a plain cart order like this one. status transitions
    are agent-driven from Textzi's own UI, each one sending an ordinary outbound template message
    to the customer (waba_orders.py) rather than relying on any Meta-side structured mechanism."""
    __tablename__ = "waba_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    conversation_message_id: Mapped[str | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    total_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WabaOrderItem(Base):
    """One line item on a WabaOrder -- copied from Meta's order.product_items at receipt time,
    never re-fetched/re-synced afterward (an order is a snapshot of what the customer actually
    ordered, not a live view of current catalog state). product_name is denormalized from
    WabaCatalogItem if a match exists at receipt time, left null otherwise -- an order referencing
    a since-deleted/renamed catalog item must still display something sensible, not break."""
    __tablename__ = "waba_order_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("waba_orders.id"), index=True)
    product_retailer_id: Mapped[str] = mapped_column(String(100))
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    item_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)


class WalletTransaction(Base):
    """Immutable ledger entry for every wallet-affecting event (recharge, message debit, manual
    adjustment, refund). `amount` is signed: positive credits the wallet, negative debits it.
    `channel` ("sms" or "waba") says which wallet this entry belongs to, since both channels
    share this one ledger table."""
    __tablename__ = "wallet_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    channel: Mapped[str] = mapped_column(String(10), default="sms")
    type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Numeric(14, 4))
    balance_after: Mapped[float] = mapped_column(Numeric(14, 4))
    reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentOrder(Base):
    """Tracks a payment-gateway order from creation to verification, binding it to the entity
    that requested it. This is what prevents a client from replaying someone else's order id, or
    from being credited for more than the amount the order was actually created for -- the amount
    credited always comes from this row (set server-side at order-creation time), never from
    whatever the client reports back after checkout."""
    __tablename__ = "payment_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # "razorpay" | "razorpay_smart_collect"
    provider_order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 4))
    purpose: Mapped[str] = mapped_column(String(30), default="wallet_recharge")
    reference_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created")
    # Snapshotted at order-creation time (wallet_recharge orders only) so a rate-card change
    # between checkout and payment verification can't change how many credits the customer
    # actually receives versus what they were quoted -- mirrors the DLT-request flow's own
    # fee-snapshot pattern.
    rate_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    price_per_sms: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Who initiated this recharge and from where -- captured at order-creation time, surfaced on
    # the admin wallet top-up reconciliation report (services.wallet_topup_report_rows).
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Snapshotted at verify-time -- the credits actually applied to the wallet for this order.
    # Compared against amount/price_per_sms (recomputed independently, not just re-read from this
    # same value) on the reconciliation report and right after crediting in payments.verify_payment,
    # so a future code change that credits a different amount than what was quoted is caught
    # immediately rather than silently drifting the ledger.
    credits_applied: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invoice(Base):
    """Every financial transaction (wallet recharge, DLT fee, channel subscription, admin manual
    credit) produces one of these. `status="draft"` only ever happens for an admin manual credit
    to someone else's entity where the admin chose not to issue immediately -- every other
    `type` goes straight to `"issued"` since those are always real charges with no ambiguity.
    `invoice_number` is only assigned at issue time (drafts don't have one yet)."""
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), default="draft")
    base_amount: Mapped[float] = mapped_column(Numeric(14, 2))
    gst_amount: Mapped[float] = mapped_column(Numeric(14, 2))
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2))
    # Set only for type="wallet_recharge" -- how many SMS credits this purchase bought and at
    # what per-SMS rate, so the Purchase Ledger can show "money in" and "credits out" on one row
    # without joining back through WalletTransaction (whose amount is credits, not rupees, and
    # has no reliable FK back to the invoice that financially represents the same purchase).
    credits_purchased: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    price_per_sms: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_admin_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Best-effort push to Zoho Books (zoho_books.py) -- never blocks or fails issue_invoice itself
    # over a Zoho-side problem. "pending" until the organization has been manually linked to Zoho
    # (admin.py's POST .../zoho-sync) AND a sync has actually been attempted -- an unlinked org's
    # invoices stay "pending" indefinitely with zero API calls, not an error; "failed" keeps
    # zoho_sync_error around so an admin can see why without digging through logs.
    zoho_invoice_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    zoho_sync_status: Mapped[str] = mapped_column(String(20), default="pending")
    zoho_sync_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Decided once at creation time (not re-derived on every sync/retry, so a retry always
    # reconciles the same way it originally would have): wallet_recharge/dlt_fee/channel_subscription
    # are only ever created after a payment is already confirmed one way or another, so they default
    # True; admin_credit is the one case where the admin themselves picks Paid or Unpaid (see
    # WalletCreditRequest.paid). True creates a matching Zoho Customer Payment, reconciled against
    # the invoice, right after it's marked sent -- zoho_payment_id tracks it the same way
    # zoho_invoice_id tracks the invoice, so a retry never creates a duplicate.
    zoho_mark_paid: Mapped[bool] = mapped_column(Boolean, default=True)
    zoho_payment_id: Mapped[str | None] = mapped_column(String(140), nullable=True)


class Invitation(Base):
    """A pending invite. Two flavors share this one table and the one accept endpoint:
    organization_id set = an existing org member inviting a teammate (accepting inherits that
    org, skipping onboarding); organization_id null = an admin inviting a new platform-staff
    account (accepting creates a user with no organization at all, matching how internal roles
    normally work)."""
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255))
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.sub_user.value)
    channel_scope: Mapped[str | None] = mapped_column(String(10), nullable=True)
    page_scope: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelSubscription(Base):
    """Whether an entity has paid the (admin-set) one-time activation price for a channel.
    `paid_at` NULL means unpaid. When the channel's ChannelFeeConfig.subscription_price is 0,
    services.channel_active() treats this condition as automatically satisfied without
    requiring a row here at all. plan_id/period_start/period_end/messages_used are the newer,
    tiered-plan path (WABA/CRM) -- set once an entity actually subscribes to a BillingPlan via
    Razorpay (channel_billing.py); services.channel_active() only starts requiring an active plan
    for a channel once that channel has at least one active BillingPlan published, so existing
    free/unpriced access isn't retroactively revoked the moment plans are introduced."""
    __tablename__ = "channel_subscriptions"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(10), primary_key=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("billing_plans.id"), nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    messages_used: Mapped[int] = mapped_column(Integer, default=0)


class BillingPlan(Base):
    """Admin-managed catalog of subscription tiers for a channel (currently WABA and CRM) --
    period is a property of the plan row itself (a "Growth" tier might have separate monthly/
    quarterly/yearly rows at different prices) rather than a multiplier applied at purchase time,
    since there's no guarantee the discount is a clean multiple. message_limit is WABA-only in
    practice (CRM plans leave it null); user_limit applies to both."""
    __tablename__ = "billing_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    channel: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(80))
    period: Mapped[str] = mapped_column(String(10))  # "monthly" | "quarterly" | "yearly"
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    message_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelSettings(Base):
    """Per-entity, per-channel privacy settings -- e.g. SMS and a future WABA channel each get
    their own independent encryption toggle rather than sharing one account-wide switch.
    `dr_webhook_url` is the customer's own delivery-report relay target -- Textzi never gives
    a customer's URL to the upstream provider directly (Tata only ever calls Textzi's one
    platform webhook); this is where Textzi forwards the delivery status to afterward, if set."""
    __tablename__ = "channel_settings"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(10), primary_key=True)
    encryption_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dr_webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class OptOutEntry(Base):
    """A customer's own self-service suppression list -- a recipient who asked not to be
    contacted again gets added here, and every send path (main.py, sms.py) checks it before
    billing or dispatching. This is deliberately NOT a claim of TRAI NCPR/DND registry
    integration -- Textzi has no API access to that government registry, and real DND/promotional
    scrubbing already happens at the network level on TTBS's own side (their scrubbing status
    codes 74-101/600-705, surfaced via DeliveryStatusCodeRule, are the actual authoritative
    signal for that). This table is the same self-service opt-out list every SMS platform
    (Twilio, MSG91, Kaleyra, ...) offers independent of any regulatory registry."""
    __tablename__ = "opt_out_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    mobile: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("entity_id", "mobile", name="uq_optout_entity_mobile"),)


class ChannelFeeConfig(Base):
    """Admin-editable fee configuration for a channel: what it costs to activate the channel
    itself, and (for SMS) what DLT registration help costs. The two DLT fee components are
    summed and shown to customers as one combined figure -- never itemised to them.

    enabled is the one global kill switch for a channel -- checked first, unconditionally, by
    services.channel_active() before any per-entity subscription/connection state. A customer
    whose own account already has an active subscription still sees the channel disappear the
    moment this is turned off; there's no per-entity override. Meant for "this channel's code is
    deployed but we're not ready to expose it to any real customer yet," not for routine
    per-customer gating (that's what ChannelSubscription is for)."""
    __tablename__ = "channel_fee_configs"
    channel: Mapped[str] = mapped_column(String(10), primary_key=True)
    subscription_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    dlt_platform_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    dlt_service_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class DltOnboardingRequest(Base):
    """A customer's request for Textzi to handle real-world DLT registration on their behalf,
    for customers who don't already have PE ID/header of their own. Real DLT registration is a
    manual, human process (submission to the telecom registry) -- this row tracks the request
    through payment and into an admin review queue; an admin completes the actual registration
    out-of-band and then creates the resulting PeId/Header via the existing DLT Hierarchy tools
    before marking this `completed`."""
    __tablename__ = "dlt_onboarding_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending_payment")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # KYC fields Tata's own telemarketer-registration process requires -- nullable so existing
    # rows from before this feature don't break, but the submit endpoint requires all of them for
    # new requests. authorized_person_aadhar is Aadhar (India's national ID number) -- Fernet-
    # encrypted at rest like TTBS credentials (security.py's encrypt_secret/decrypt_secret), never
    # returned to any API response in plaintext, only masked (services.mask_aadhar).
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    company_gst: Mapped[str | None] = mapped_column(String(15), nullable=True)
    authorized_signatory_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authorized_person_aadhar_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    dlt_platform_fee: Mapped[float] = mapped_column(Numeric(12, 2))
    dlt_service_fee: Mapped[float] = mapped_column(Numeric(12, 2))
    gst_amount: Mapped[float] = mapped_column(Numeric(12, 2))
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2))
    payment_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DltOnboardingRequestDocument(Base):
    __tablename__ = "dlt_onboarding_request_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(ForeignKey("dlt_onboarding_requests.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(300))
    # "supporting" (company registration, ID proof, etc.) or "authorization_letter" -- the signed
    # Tata declaration letter is functionally distinct (it has its own required upload + a
    # downloadable fillable sample) and needs to be shown separately in the admin review UI, not
    # mixed in anonymously with the general supporting-documents pile.
    document_type: Mapped[str] = mapped_column(String(50), default="supporting")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileChangeRequest(Base):
    """A customer's request to change their own or their organization's identity fields (name,
    email, mobile, GST/company details) -- these aren't directly self-editable (unlike the
    one-time initial company-profile submission in onboarding.py), so a change instead queues
    here for admin review, same request/approval shape as DltOnboardingRequest above. Unlike that
    one, approval here auto-applies the change (admin.py's review endpoint writes straight to the
    User/Organization rows) rather than requiring the admin to separately go make the change
    elsewhere -- there's no external, out-of-band process involved in renaming a user or updating
    a GSTIN, so there's no reason to make the admin do it twice.

    Every requested_* column is nullable -- only the fields the customer actually wants changed
    are set, the rest stay null and are left untouched on approval."""
    __tablename__ = "profile_change_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_full_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    requested_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requested_company_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    requested_gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    requested_pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    requested_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    requested_state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    customer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoutePolicy(Base):
    __tablename__ = "route_policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    routes: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", name="uq_route_policy_subject"),)


class ProviderRoute(Base):
    """Binds a route name used in RoutePolicy.routes to an outbound provider connection, so
    dispatch can reach a distinct provider per named route instead of one shared credential.
    `provider_type` selects which SmsProvider implementation applies; provider-specific fields
    (including encrypted secrets) live in `config`."""
    __tablename__ = "provider_routes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    route_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    provider_type: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"))
    # Text, not String(20) -- when is_encrypted is True this holds a Fernet token (encrypt_secret's
    # output), which is far longer than any real phone number. Same encrypt-at-rest treatment as
    # rendered_body, decrypted right before an actual send (dispatch.py) or a masked display
    # (sms.py/admin.py) -- previously this was stored in plaintext regardless of the encryption
    # toggle, which only ever encrypted the message body.
    recipient: Mapped[str] = mapped_column(Text)
    rendered_body: Mapped[str] = mapped_column(Text)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    route: Mapped[str | None] = mapped_column(String(100), nullable=True)
    route_plan: Mapped[list] = mapped_column(JSON, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Segment-based billing (services.sms_segment_credits): 1 credit per 160 characters of the
    # rendered body, rounded up. Stored explicitly (not recomputed later) so a failed-delivery
    # refund -- either dispatch.py's immediate all-routes-failed path or webhooks.py's DR-status
    # path -- always credits back exactly what was actually charged, even for a multi-segment
    # message, instead of a hardcoded 1.
    credits_charged: Mapped[int] = mapped_column(Integer, default=1)
    # Full telemetry for the admin SMS Log & Report "View" drill-down -- the inbound /v1/sms/send
    # request as received (recipient/variables masked or omitted whenever is_encrypted is set, so
    # the encryption promise holds in storage, not just in what a later API response chooses to
    # show) and the SmsSendResponse actually returned. Neither contains anything a route-level
    # DeliveryAttempt wouldn't also need its own copy of -- this is the customer-facing half of
    # the request/response chain, DeliveryAttempt is the provider-facing half.
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set by archiving.py once this row (plus its DeliveryAttempts/ApiLog) has been written to the
    # local gzip archive and its heavy fields nulled out here -- the idempotency marker for
    # re-running the archive job (skip anything already archived). The row itself and its
    # lightweight reporting fields are never deleted, so reports.py's export endpoint always reads
    # straight from this table regardless of how old the range is.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("entity_id", "idempotency_key", name="uq_message_idempotency"),
        # Backs reports.py's export query and channels.py's dashboard summary (both filter by
        # entity_id, order/range by created_at) -- without this, both degrate to a scan of the
        # single-column entity_id index followed by an in-memory sort/filter as the table grows.
        Index("ix_messages_entity_created", "entity_id", "created_at"),
        # Backs archiving.archive_to_local()'s daily WHERE archived_at IS NULL AND created_at <
        # cutoff scan -- without this it's a full table scan once the hot tier grows past a few
        # months.
        Index("ix_messages_archived_created", "archived_at", "created_at"),
    )


class ArchiveManifest(Base):
    """One row per archive file this app has ever written -- both the local gzip+JSONL tier and
    the Parquet-on-R2 tier. The source of truth for "has this month already been archived/
    promoted" (idempotency for archiving.py's daily job), and for archiving.read_archived_rows()
    to know which tier holds a given month's full raw telemetry, without probing the
    filesystem/R2 on every lookup."""
    __tablename__ = "archive_manifest"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tier: Mapped[str] = mapped_column(String(10))  # "local" | "r2"
    period: Mapped[str] = mapped_column(String(7))  # "YYYY-MM", the month this file covers
    path: Mapped[str] = mapped_column(String(500))  # local filesystem path, or R2 object key
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("tier", "period", name="uq_archive_tier_period"),)


class ArchiveRunLog(Base):
    """Every attempt at running the daily archive job (archive_jobs.run()), one row per step
    (local/r2), whether it succeeded or not -- unlike ArchiveManifest above, which only ever
    records a *successful* period-completion and has no idea whether the job even ran today.
    This is what actually answers "did the job run, and did it work" for the admin archive-status
    page, mirroring ZohoApiCallLog's success-or-failure-both-logged pattern."""
    __tablename__ = "archive_run_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job: Mapped[str] = mapped_column(String(10))  # "local" | "r2"
    status: Mapped[str] = mapped_column(String(10))  # "success" | "failed" | "partial"
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountActivity(Base):
    """Security/account-level audit trail -- logins, lockouts, 2FA changes, team invites, role
    changes, and admin-panel mutations. Deliberately separate from ApiLog (which tracks the SMS
    sending API, keyed by entity_id) and WalletTransaction (money/credits) -- this table is about
    who did what to an account or the platform itself. organization_id is set for anything scoped
    to one customer (so an org owner can see activity across their own org's users via Reports);
    it's null for admin-only actions with no single target org (a rate card change, a platform
    settings update) -- those only ever show up in the cross-org admin audit log."""
    __tablename__ = "account_activity"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiLog(Base):
    __tablename__ = "api_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(160))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # The caller's own request fingerprint -- client_ip(request)/CF-IPCountry/User-Agent were
    # already being computed in main.py's send endpoints (client_ip for the API-key IP allow-list
    # check) but silently discarded before logging; now persisted so the admin API Log report can
    # actually show who/where/what called in, not just the outcome. Only set on single-send
    # (message_id links this call to the one Message it created) -- bulk creates many Messages
    # per call, so there's no single row to link to and it's left null there.
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country: Mapped[str | None] = mapped_column(String(4), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryAttempt(Base):
    """One attempt to hand a message to one provider route. `entity_id` is denormalized from
    Message (rather than joined every time) so the DR webhook handler can resolve the customer
    and their webhook config directly from provider_message_id alone -- no extra join. `status`
    starts as "submitted"/"failed" at send time and is overwritten in place once a delivery
    report arrives ("delivered"/"delivery_failed") -- "submitted" was always meant to be
    transient. `provider_message_id` (TTBS's own SubmissionID/jobId) is the correlation key an
    inbound DR callback is looked up by -- already unique, no new lookup table needed."""
    __tablename__ = "delivery_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    route: Mapped[str] = mapped_column(String(100))
    provider_message_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    delivery_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Full telemetry for the admin SMS Log & Report "View" drill-down. request_payload is the
    # params actually sent to the provider (any credential already redacted by the provider
    # adapter itself -- see providers.py -- before it's ever assigned here); response_body is the
    # provider's raw response text; webhook_payload is the raw DR callback body once one arrives
    # (null until then, and for any route that never requested delivery reports at all).
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The OTHER direction: webhook_payload above is what TTBS sent US; these track what WE then
    # relayed on to the customer's own ChannelSettings.dr_webhook_url (webhooks.py's
    # _relay_to_customer) -- previously fire-and-forget with zero record of whether it was even
    # attempted, let alone whether it succeeded, confirmed live: a customer could report "we never
    # got your delivery report" and there was no way to check what Textzi actually sent or why it
    # failed. customer_webhook_status is one of "not_configured" | "success" | "failed".
    customer_webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    customer_webhook_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    customer_webhook_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_webhook_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    customer_webhook_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryStatusCodeRule(Base):
    """Admin-configured billing outcome for a provider's DeliveryStatusCode (TTBS's DR/scrubbing
    codes -- 0-11, 74-101, 600-705, etc). A code NOT listed here defaults to a billable success
    (message counted delivered, the wallet debit from send time stands). Only codes explicitly
    added here are treated as a failed send; `refund` then decides whether that failure also
    credits the customer's wallet back."""
    __tablename__ = "delivery_status_code_rules"
    code: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    refund: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- Platform-internal infrastructure: deliberately independent of Organization/Entity/Message.
# The platform sends its own operational messages (login OTPs) and email (verification, invoices,
# invites) under its own identity, funded by its own wallet -- never modeled as "just another
# tenant" the way an earlier iteration of this feature did. ----

class PlatformWallet(Base):
    """Singleton row (id is always "platform"). Internal use only -- a simple credit pool an
    admin tops up directly, no rupee-to-credit conversion, no GST, no invoicing."""
    __tablename__ = "platform_wallet"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0)


class PlatformWalletTransaction(Base):
    __tablename__ = "platform_wallet_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    balance_after: Mapped[float] = mapped_column(Numeric(14, 2))
    reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformSmsSettings(Base):
    """Singleton row. The platform's own DLT sender identity, used only for its own operational
    SMS (currently: login OTPs) -- never exposed anywhere in the tenant DLT Hierarchy UI."""
    __tablename__ = "platform_sms_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    pe_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pe_operator: Mapped[str | None] = mapped_column(String(80), nullable=True)
    header_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sender_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dlt_template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    template_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    route: Mapped[str | None] = mapped_column(String(100), nullable=True)


class PlatformSmtpSettings(Base):
    """Singleton row. Every platform-to-user email (verification codes, invoices, team invites)
    routes through this one config -- editable from the admin UI, not just `.env`."""
    __tablename__ = "platform_smtp_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=587)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    from_address: Mapped[str] = mapped_column(String(255), default="no-reply@textzi.in")
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True)


class PlatformR2Settings(Base):
    """Singleton row. Cloudflare R2 (S3-compatible object storage) credentials for the cold-tier
    archive promotion in archiving.py -- editable from the admin UI, not just `.env`, same
    convention as PlatformSmtpSettings above. secret_access_key is write-only (encrypted at rest,
    never returned by GET); account_id/access_key_id/bucket_name aren't secrets in the same sense
    (an access key ID is an identifier, not a credential) so they're stored and returned plain."""
    __tablename__ = "platform_r2_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    secret_access_key_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bucket_name: Mapped[str | None] = mapped_column(String(128), nullable=True)


class PlatformTurnstileSettings(Base):
    """Singleton row. Cloudflare Turnstile credentials for the bot-check widget embedded on
    register/login/forgot-password/contact -- editable from the admin UI, not just `.env`, same
    convention as PlatformSmtpSettings/PlatformR2Settings above. site_key isn't a secret (it ships
    to every visitor's browser regardless) so it's stored/returned plain, via the public
    /v1/public/turnstile-config endpoint the frontend fetches at runtime; secret_key is write-only
    (encrypted at rest, never returned by GET)."""
    __tablename__ = "platform_turnstile_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    site_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_key_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PlatformRazorpaySettings(Base):
    """Singleton row. Live Razorpay credentials for wallet recharge + channel-billing checkout
    (payments.py, channel_billing.py, channels.py, admin.py) -- admin-UI-editable, same convention
    as PlatformSmtpSettings above, superseding the .env-only Settings.razorpay_key_* fields (those
    stay the fallback until this row is configured, same fallback contract as
    get_platform_company_info -- this is on production for SMS today, so the .env values must keep
    working unchanged until an admin explicitly saves here). key_secret is write-only (encrypted
    at rest, never returned by GET); key_id isn't a secret in the same sense (it's echoed back to
    the browser on every order-create call already) so it's stored plain."""
    __tablename__ = "platform_razorpay_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    key_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    key_secret_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Separate from key_id/key_secret above -- this is the secret configured in Razorpay
    # Dashboard > Webhooks specifically for Smart Collect's virtual_account.credited event, used
    # to verify X-Razorpay-Signature the same way app_secret verifies Meta's X-Hub-Signature-256
    # in waba_webhooks.py. Never returned by GET.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PlatformZohoSettings(Base):
    """Singleton row. Connection details for Zoho Books -- Zoho is the source of truth for the
    invoice DOCUMENT itself (zoho_books.py creates the Contact/Item/Invoice there and fetches the
    rendered PDF back); Textzi's own fpdf2 rendering (invoicing.py) only ever runs as a fallback
    when Zoho is unconfigured, an organization hasn't been linked yet, or a call fails, so a
    customer is never left with literally no invoice while a failure is retried. Auth is OAuth2
    self-client (api-console.zoho.com) rather than a static key/secret: client_id/client_secret
    are entered once, then a one-time grant/authorization code is exchanged (POST
    /v1/admin/platform/zoho-connect) for a non-expiring refresh token; access_token_encrypted +
    access_token_expires_at are then maintained automatically by zoho_books._access_token. The
    item_code_sms_service/item_code_platform_fee_dlt/item_code_platform_fee_whatsapp map Textzi's
    Invoice.type values (grouped via services.INVOICE_TYPE_ITEM_GROUP) to a Zoho Item id each --
    auto resolved (by name) or created the first time it's needed. gst_tax_id_intrastate/interstate are real Zoho
    tax_id GUIDs (fetched via GET .../zoho-tax-rates) -- picked per invoice based on whether the
    customer's state matches the platform's own home state (services.get_platform_company_info's
    company_state_code, the same field the invoice PDF's seller block already uses)."""
    __tablename__ = "platform_zoho_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # e.g. "www.zohoapis.in" / "accounts.zoho.in" -- captured from the token-exchange response at
    # Connect time (Zoho's own source of truth for which data center this org lives on), not
    # hand-typed, though still editable if it's ever wrong.
    api_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accounts_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gst_tax_id_intrastate: Mapped[str | None] = mapped_column(String(140), nullable=True)
    gst_tax_id_interstate: Mapped[str | None] = mapped_column(String(140), nullable=True)
    # Zoho requires a tax_id (or an explicit tax-exemption reason) on every line item once GST
    # compliance is enabled for the org -- confirmed live, "Specify either a Tax or Tax Exemption"
    # -- so a zero-GST invoice (e.g. a free/promotional admin_credit) still needs a real 0% tax
    # rate attached, not an omitted tax_id. A single 0% rate (e.g. Zoho's own pre-provisioned
    # "GST0"), not split intrastate/interstate like the real rates above -- 0% has no CGST/SGST
    # vs IGST distinction that matters here.
    gst_tax_id_zero_rated: Mapped[str | None] = mapped_column(String(140), nullable=True)
    # The Zoho Books Bank/Cash account a Customer Payment deposits into -- required before any
    # invoice marked zoho_mark_paid=True can actually sync; picked by the admin from a real
    # fetched list (GET .../zoho-accounts), not free text.
    payment_deposit_account_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    item_code_sms_service: Mapped[str | None] = mapped_column(String(140), nullable=True)
    item_code_platform_fee_dlt: Mapped[str | None] = mapped_column(String(140), nullable=True)
    item_code_platform_fee_whatsapp: Mapped[str | None] = mapped_column(String(140), nullable=True)


class ZohoApiCallLog(Base):
    """Every Zoho Books API call Textzi makes, success or failure -- the admin-visible history
    that lets an admin see exactly what happened and why before retrying (zoho_books.py logs one
    row per HTTP call, not one per invoice, so a single invoice's Contact + Item + Invoice +
    mark-sent + payment + PDF-fetch chain shows as its own timeline of attempts)."""
    __tablename__ = "zoho_api_call_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformGeneralSettings(Base):
    """Singleton row. Deployment-specific but non-secret operational config, editable from the
    admin UI instead of requiring a .env change + container redeploy -- invoice/company details,
    the support inbox, and this API's own externally-reachable base URL (used to build provider
    DR webhook URLs). Every column is nullable and falls back to the .env default in config.py
    when unset, so an unconfigured deployment behaves exactly as it did before this table
    existed."""
    __tablename__ = "platform_general_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    company_state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    company_state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    company_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    support_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_api_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PlatformMessage(Base):
    """The platform's own message log -- independent of the tenant `messages` table (no
    entity_id FK)."""
    __tablename__ = "platform_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    purpose: Mapped[str] = mapped_column(String(30))
    recipient: Mapped[str] = mapped_column(String(20))
    rendered_body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="accepted")
    route: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Same telemetry pair as DeliveryAttempt.request_payload/response_body -- platform sends are
    # one-shot (no failover route list, no separate attempt table), so they're stored directly
    # here instead.
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Same DR fields as DeliveryAttempt -- added after the webhook's PlatformMessage fallback
    # branch was found to set status="delivered" without ever recording what TTBS actually sent,
    # making it impossible to tell a genuine delivery from an unmapped DeliveryStatusCode
    # defaulting to "delivered" (see DeliveryStatusCodeRule).
    delivery_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    webhook_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactMessage(Base):
    """A submission from the public marketing site's Contact form. Persisted so nothing is
    lost if the support-inbox email fails or SMTP isn't configured; also emailed to the
    platform's configured support address (PlatformGeneralSettings, falling back to
    config.settings.support_email) as the primary channel support staff actually watch."""
    __tablename__ = "contact_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Testimonial(Base):
    """A quote shown on the public landing page's Testimonials section. Two ways in: a logged-in
    customer submits one about their own experience (status starts "pending", organization_id/
    submitted_by_user_id set, requires admin approval before it's ever public), or an admin
    authors one directly (status "approved" immediately, both id columns null -- e.g. entering a
    quote a customer emailed in rather than submitted through the form). Either way, only
    status == "approved" rows are ever returned by the public endpoint."""
    __tablename__ = "testimonials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    submitted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(120))
    author_role: Mapped[str] = mapped_column(String(160))
    quote: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VisitorSession(Base):
    """One browser (identified by a first-party cookie, not a person) across however many pages
    it views on the public site. user_id is only ever filled in retroactively -- if that same
    browser later registers or logs in, request_visitor_beacon links this session forward, so an
    anonymous visit can be connected to the account it eventually became without ever having
    tracked identity before that point. country is Cloudflare's own CF-IPCountry header (already
    in front of this deployment) -- deliberately not a paid GeoIP database, since country-level is
    already what that header gives for free and city-level precision isn't something this needs
    or should be collecting from anonymous visitors. See privacy-policy.vue Section 1/7 for the
    public disclosure this is built to match."""
    __tablename__ = "visitor_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(40), nullable=True)
    os: Mapped[str | None] = mapped_column(String(40), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    first_referrer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PageView(Base):
    """One page load within a VisitorSession -- path/referrer/viewport only, no click-level or
    cross-site tracking."""
    __tablename__ = "page_views"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("visitor_sessions.id"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    referrer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    viewport_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    viewport_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# ---------------------------------------------------------------------------------------------
# Native shared inbox (Phase A of the WABA/native-messaging plan) -- WhatsApp today, Email next.
# Deliberately separate from every SMS/DLT table above: no FK from here into Message/Template/
# PeId/Header, and nothing above ever references these. A bug in the inbox can't touch SMS.
# ---------------------------------------------------------------------------------------------

class Company(Base):
    """A B2B account a Contact can belong to -- "multiple contacts per company" (e.g. a business's
    owner, accountant, and store manager all messaging in separately) needs this rollup; without
    it there's no way to see them as one account. Kept deliberately thin (name + a few identity
    fields) rather than duplicating Organization's own GST/PAN fields -- a Company here is the
    tenant's *customer's* business, not Textzi's own tenant."""
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(80), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Account Owner -- Zoho/SF both use this to drive territory visibility and "my accounts"
    # filtering; every Company was equally visible to everyone until this field existed.
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "customer"|"partner"|"prospect"|"vendor"
    # Subsidiary-under-parent nesting (Zoho/SF's Parent Account) -- e.g. a regional branch rolled
    # up under its head office. Self-referential, nullable since most SME accounts are flat.
    parent_company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_revenue: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    """A person Textzi has exchanged messages with on behalf of an entity -- WhatsApp today
    (identified by wa_id, Meta's own WhatsApp ID for the number), email accounts later
    (identified by email address instead). custom_attributes is a JSON blob, not fixed columns --
    confirmed this session that every competitor WABA platform researched (WATI/Interakt/
    AiSensy/Gallabox) supports arbitrary custom fields per contact, not a rigid schema, so a
    fixed-column design would mean a migration every time a customer wants to track one more
    thing about their own contacts."""
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    wa_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    custom_attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    # WhatsApp-specific opt-out -- a contact who's opted out must never receive another outbound
    # message on this channel regardless of what any agent/automation/campaign tries to send.
    # Deliberately its own column, not a custom_attributes entry, since enforcement code needs to
    # read it on every single send without trusting a free-form JSON blob's shape.
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set when this contact is known to be the same real-world person/business as an existing
    # CRM Customer -- either automatically (this contact was the one converted) or explicitly via
    # "map to existing customer" (a second contact/number for a customer already converted from a
    # different conversation). Many contacts can point at one Customer; a Customer's own
    # contact_id is still the contact it was originally converted from.
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    # DPDP Act (India's data protection law) -- consent_given_at null means no explicit consent on
    # record (a WhatsApp contact who's simply messaged in has implicit consent for that
    # conversation under DPDP's "legitimate use" ground; this is for an explicit opt-in, e.g. to a
    # marketing segment/campaign). consent_source is free text (e.g. "whatsapp_optin_form",
    # "manual_entry") for the audit trail DPDP expects.
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Set when this WhatsApp contact has been explicitly converted into CRM (convert-to-lead/
    # deal/customer) -- CRM owns a genuinely separate contact record (CrmContact, below) rather
    # than reusing this WABA-owned row, per the user's explicit "whatsapp have own and crm have
    # own... if from whatsapp we convert in crm" decision. Same bridge shape as customer_id above,
    # one step earlier in the funnel.
    crm_contact_id: Mapped[str | None] = mapped_column(ForeignKey("crm_contacts.id"), nullable=True)
    # Webchat identity: a browser-generated UUID the widget persists in localStorage, sent on
    # every request -- the only identity a brand-new anonymous website visitor has (no phone/
    # email until they choose to give one). Set the first time a visitor's widget session sends an
    # actual message (see webchat_public.py) -- not created on every page view.
    visitor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # One Contact row per (entity, WhatsApp number) -- prevents the same inbound number from
        # ever silently fragmenting into two separate contact records for one entity.
        UniqueConstraint("entity_id", "wa_id", name="uq_contacts_entity_wa_id"),
        # Same guarantee for email-identified contacts (crm_email.py's inbound poll/send find-or-
        # create) -- NULL values don't collide with each other under Postgres unique-constraint
        # semantics, same as wa_id above, so a WhatsApp-only contact with no email is unaffected.
        UniqueConstraint("entity_id", "email", name="uq_contacts_entity_email"),
        # Same guarantee for webchat visitors, identified by visitor_id instead of wa_id/email.
        UniqueConstraint("entity_id", "visitor_id", name="uq_contacts_entity_visitor_id"),
    )


class Conversation(Base):
    """One open/pending/resolved thread with a Contact on a specific channel. status is the
    near-universal three-state pattern across every shared-inbox tool researched this session
    (Chatwoot, and the category generally) -- not WhatsApp/Meta's own concept, purely Textzi's
    own inbox-management state."""
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    status: Mapped[str] = mapped_column(String(20), default="open")
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set whenever an agent opens this conversation -- distinct from any individual message's own
    # delivery `status`, since "has an agent seen this" is a conversation-level fact, not
    # per-message. Drives both the unread indicator and whether a read receipt gets sent to Meta.
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Not every conversation needs formal tracking -- a lot of WhatsApp traffic is a quick
    # back-and-forth that doesn't warrant it. is_ticket is an explicit, agent-driven upgrade
    # ("Convert to ticket"): general chats stay plain (this flag off, no ticket_number), tickets
    # get a human-readable sequential number (waba_inbox.convert_conversation_to_ticket, same
    # nextval()-backed sequence pattern as invoicing.py's invoice numbers) and show up in the
    # dedicated Tickets view in addition to the regular inbox.
    is_ticket: Mapped[bool] = mapped_column(Boolean, default=False)
    ticket_number: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    ticket_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set from SlaPolicy.first_response_minutes the moment a new inbound message opens this
    # conversation with no reply yet; cleared (both to null) the moment an agent's first outbound
    # reply lands. sla_breached is stamped true (and left true, as a historical record) if
    # first_response_due_at passes with no reply -- computed opportunistically wherever a
    # conversation is read, not by a background job.
    first_response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    # Resolution SLA mirrors the first-response one exactly -- set from SlaPolicy.resolution_minutes
    # the same moment a conversation becomes a ticket, stamped breached (and left true, a
    # historical record) the same opportunistic way, computed wherever a conversation is read.
    resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    # Freshdesk-style ticket fields -- only meaningful once is_ticket is true, but not worth a
    # separate table for (same "extra columns on the existing row" pattern as Lead/Deal's own
    # qualification fields).
    priority: Mapped[str] = mapped_column(String(10), default="medium")  # "low"|"medium"|"high"|"urgent"
    category: Mapped[str] = mapped_column(String(20), default="question")  # "question"|"incident"|"problem"|"task"
    group_id: Mapped[str | None] = mapped_column(ForeignKey("ticket_groups.id"), nullable=True)
    ticket_custom_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    # Editable independently of any one message's own body/subject -- Freshdesk/Salesforce both
    # let an agent set a ticket's subject/case title directly rather than inferring one from
    # whatever the customer's first message happened to say. Null falls back to the last message
    # preview in the UI, same as today's behavior before this field existed.
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Extra recipients CC'd on outbound replies for an email-channel ticket -- plain list, same
    # "no join table needed at this scale" reasoning as TicketGroup.member_user_ids.
    cc_emails: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Stamped the moment status first becomes "resolved" (cleared back to null if reopened) --
    # without this, actual resolution time can't be computed after the fact at all (only whether
    # resolution_due_at was breached, never how long it really took), which reporting needs.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Every find-or-create site (waba_dispatch.py, waba_webhooks.py, crm_email.py) already
        # treats (entity, contact, channel) as unique -- this is what actually enforces it, closing
        # a race where two concurrent first-contact events (e.g. an inbound email poll racing an
        # outbound send to the same brand-new contact) could otherwise create two Conversation rows.
        UniqueConstraint("entity_id", "contact_id", "channel", name="uq_conversations_entity_contact_channel"),
    )


class TicketGroup(Base):
    """Freshdesk's "Groups" -- a named team a ticket can be routed to, alongside (not instead of)
    per-ticket assigned_user_id. member_user_ids is a plain JSON list rather than a join table,
    same reasoning as Territory.pincodes -- membership here doesn't need relational integrity at
    this scale, just a settings-page list an admin edits directly."""
    __tablename__ = "ticket_groups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    member_user_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationMessage(Base):
    """One message (real, customer/agent-facing) or private note (internal only) within a
    Conversation. meta_message_id is Meta's own wamid -- indexed so an incoming status webhook
    (sent/delivered/read/failed) can find the row it's updating; nullable because inbound
    messages and internal notes don't have one from our side to correlate against (inbound
    messages get their own wamid from Meta, stored the same way, just never used for a status
    update since Meta doesn't send delivery receipts for messages it sent to us)."""
    __tablename__ = "conversation_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "inbound" | "outbound"
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    message_type: Mapped[str] = mapped_column(String(20), default="text")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Structured content for message types that don't fit body/media_url -- shape depends on
    # message_type: location -> {latitude, longitude, name, address}; contacts -> Meta's own
    # contacts array as-is; interactive_button/interactive_list (outbound) -> the buttons/rows
    # offered; button_reply/list_reply (inbound) -> {id, title} of what the customer picked;
    # reaction -> {emoji, reacted_to_wamid}. One flexible JSON column rather than a handful of
    # sparse nullable ones per type, same reasoning as Contact.custom_attributes.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # sent|delivered|read|failed, outbound only
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sent_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Label(Base):
    """A tag definition, scoped to either conversations or contacts -- kept as two logically
    distinct pools (scope="conversation" vs scope="contact") even though they share one table,
    since every competitor platform researched this session treats "urgent" (a conversation-level
    label) and "VIP customer" (a contact-level label) as different concepts, not one shared tag
    list that happens to apply to two kinds of things."""
    __tablename__ = "labels"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    scope: Mapped[str] = mapped_column(String(20))  # "conversation" | "contact"
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(20), default="primary")

    __table_args__ = (
        UniqueConstraint("entity_id", "scope", "name", name="uq_labels_entity_scope_name"),
    )


class ConversationLabel(Base):
    __tablename__ = "conversation_labels"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    label_id: Mapped[str] = mapped_column(ForeignKey("labels.id"), primary_key=True)


class ContactLabel(Base):
    __tablename__ = "contact_labels"
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), primary_key=True)
    label_id: Mapped[str] = mapped_column(ForeignKey("labels.id"), primary_key=True)


class CannedResponse(Base):
    """A saved `/shortcut` -> message-body pair. body may contain {{contact.name}}/
    {{agent.name}} placeholders -- confirmed this session as the baseline variable set every
    competitor platform supports; resolved at send time, not stored pre-filled."""
    __tablename__ = "canned_responses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    shortcut: Mapped[str] = mapped_column(String(25))
    body: Mapped[str] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("entity_id", "shortcut", name="uq_canned_responses_entity_shortcut"),
    )


class AutomationRule(Base):
    """A single trigger -> action rule, evaluated in `priority` order against every new inbound
    message (waba_webhooks.py). Deliberately one action per rule rather than a multi-step tree --
    that's the WhatsApp-Flow-style bot builder the plan scoped separately as its own product
    surface (Phase B), not this. trigger_value/action_value are plain strings whose meaning
    depends on the type (trigger_value is the keyword to match for "keyword", unused for
    "new_contact"/"outside_hours"; action_value is a user_id/canned_response_id/label_id depending
    on action_type) -- avoids a wide sparse-column table for what's fundamentally a handful of
    small variants."""
    __tablename__ = "automation_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    trigger_type: Mapped[str] = mapped_column(String(20))  # "keyword" | "new_contact" | "outside_hours"
    trigger_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    action_type: Mapped[str] = mapped_column(String(20))  # "assign" | "reply" | "label"
    action_value: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------------------------
# CRM (3rd channel, gated by channel_active(db, entity_id, "crm")) -- owns its own CrmContact,
# genuinely separate from the WhatsApp-owned Contact above. The two are bridged only by an
# explicit "convert" action (Contact.crm_contact_id, set at conversion time), never a shared row
# -- matches the "whatsapp have own and crm have own... if from whatsapp we convert in crm"
# decision, and the same "real separate objects connected by Convert" principle already applied
# to the Lead/Deal split below.
# ---------------------------------------------------------------------------------------------

class CrmContact(Base):
    """CRM's own person record -- decoupled from WhatsApp entirely, so a lead/deal/customer added
    directly in CRM doesn't need (and doesn't get) a WhatsApp identity until someone actually
    messages them. phone is a plain field here, not a wa_id: sending a WhatsApp message to this
    contact resolves/creates the WABA Contact just-in-time from this number (see
    waba_dispatch._resolve_send_target, already built to do exactly this for any wa_id it hasn't
    seen), so nothing about that capability is lost by not sharing the WABA Contact row."""
    __tablename__ = "crm_contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Contact Owner -- same territory/"my contacts" reasoning as Company.owner_user_id above;
    # Lead/Deal/Customer all already had one, Contact was the odd one out.
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Self-referential contact hierarchy (Zoho/SF's "Reports To") -- e.g. an assistant linked to
    # the executive they support. Nullable, most contacts have none.
    reports_to_id: Mapped[str | None] = mapped_column(ForeignKey("crm_contacts.id"), nullable=True)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(40), default="manual")  # "whatsapp_conversation" | "manual" | "web_form" | "csv_import"
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Real dedup guard for _resolve_or_create_contact's find-or-create -- a plain SELECT-then-INSERT
    # has a race window under concurrent requests for the same never-before-seen phone number.
    # Partial (phone IS NOT NULL) since phone is optional and many contacts share NULL.
    # sync_schema only emits plain (non-unique, non-partial) CREATE INDEX, so these are created
    # manually -- see the manual ALTER note in services.py's _resolve_or_create_contact usage.
    # Same guarantee for email, closing the identical race in crm_public.py's unauthenticated
    # web-form submission endpoint (confirmed exploitable: concurrent/retried form submits for a
    # brand-new email created multiple CrmContact rows before this index existed).
    __table_args__ = (
        Index("uq_crm_contacts_entity_phone", "entity_id", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")),
        Index("uq_crm_contacts_entity_email", "entity_id", "email", unique=True, postgresql_where=text("email IS NOT NULL")),
    )


class Pipeline(Base):
    """A named, ordered stage list an entity's deals move through -- an entity can have more than
    one (e.g. "New Business" vs "Renewals"). Replaces CrmSettings.pipeline_stages as the source of
    truth; that column's existing data gets migrated into one auto-created "Default" pipeline per
    entity so nothing already using it breaks. Each stage carries its own probability/forecast
    category (Zoho/Salesforce convention) rather than deriving one from stage order, since two
    pipelines can reuse the same stage name at different probabilities."""
    __tablename__ = "pipelines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    # [{"name": str, "probability": int, "forecast_category": "pipeline"|"commit"|"omitted"}, ...]
    stages: Mapped[list] = mapped_column(JSON, default=lambda: list(DEFAULT_CRM_PIPELINE_STAGES))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Deal(Base):
    """A qualified sales opportunity for a Contact -- what this codebase called "Lead" before the
    Zoho/Salesforce-parity split (see Lead below). Reachable either by converting a Lead
    (converted_from_lead_id set) or directly from a WhatsApp conversation when an agent already
    knows the contact is qualified (converted_from_conversation_id set, converted_from_lead_id
    null) -- both paths land here, matching the "no forced Lead-first requirement" decision made
    when Customer conversion was first built. stage is free-text (not an enum) since a payments
    business's own stage names (inquiry/KYC/onboarding/live/renewal) are a product decision, not a
    platform one -- validated against pipeline.stages at write time, not a DB-level constraint, so
    the pipeline's own stage list can change without a migration. value/probability drive the
    forecast/pipeline-value reporting; status separately tracks won/lost since a deal can lose from
    any stage, not just a terminal one."""
    __tablename__ = "deals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    # Distinct from the contact's own name -- matches Zoho/SF's Opportunity Name, since one
    # contact can have more than one deal over time (a renewal alongside a new sale) and they'd
    # otherwise be indistinguishable in every list. Null falls back to the contact's name in the
    # UI, same "display fallback, not a required field" pattern as Conversation.subject above.
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(40), default="inquiry")
    source: Mapped[str] = mapped_column(String(40), default="manual")  # "whatsapp_conversation" | "manual" | "csv_import"
    converted_from_conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    converted_from_lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    probability: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # "open" | "won" | "lost"
    lost_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Lightweight "what happens next" field -- Zoho/Salesforce both treat this as a first-class,
    # heavily-used field distinct from the free-text notes below (a running log), not a
    # replacement for it.
    next_step: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_step_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    # {stage_name: [{"user_id": ..., "approved_at": ...}, ...]} -- who has signed off on leaving
    # each stage so far. Only checked against a stage's own required_approval_user_ids (Pipeline.
    # stages) when actually leaving that stage; same shape as Quote.approvals, just keyed per
    # stage rather than a single flat list, since a deal can pass through the same pipeline more
    # than once (e.g. reopened) and each pass needs its own sign-off record.
    stage_approvals: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DealStageEvent(Base):
    """One row per stage a Deal has ever sat in -- exited_at null means "currently in this
    stage". Lets Reports answer "how long do deals sit in KYC on average", which Zoho/SF both
    track natively and this schema had no way to answer before (Deal.stage is just the current
    value, with no history). A row is opened the moment a Deal is created and whenever its stage
    changes (crm.py's update_deal_stage closes the previous open row first)."""
    __tablename__ = "deal_stage_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Who caused this row to open (stage change, pipeline change, or deal creation) -- null for the
    # very first event opened at Deal creation before any user action, and for system-driven opens.
    changed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Lead(Base):
    """An unqualified, top-of-funnel record for a Contact -- name/company/source/status only, no
    deal value or pipeline stage (those only exist once a Lead is converted into a Deal, see
    above). Matches Zoho's Lead.Company (free text, pre-conversion) and Salesforce's Lead/
    Opportunity separation, per the user's explicit "Full split (matches Zoho/SF exactly)" choice.
    company_name is deliberately free text, not a Company FK, since a raw lead's business often
    isn't a real linked Company record yet."""
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    company_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")  # "whatsapp_conversation" | "manual" | "web_form" | "csv_import"
    status: Mapped[str] = mapped_column(String(12), default="new")  # "new" | "contacted" | "qualified" | "unqualified" | "converted"
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    # Rule-based (not AI/ML) lead score -- sum of ScoringRule.points for every rule this lead
    # currently matches, recomputed on every relevant change (label added, custom field set,
    # activity logged) by crm_scoring.rescore_lead rather than stored as a decaying/time-based
    # score, keeping it simple and fully explainable to the sales rep.
    score: Mapped[int] = mapped_column(Integer, default=0)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_deal_id: Mapped[str | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScoringRule(Base):
    """One rule contributing points to Lead.score -- e.g. "has label VIP" +20, "custom field
    budget > 100000" +15. Deliberately simple point-sum scoring (matches the standing "no AI/LLM"
    instruction) rather than a predictive model."""
    __tablename__ = "scoring_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    condition_type: Mapped[str] = mapped_column(String(20))  # "has_label" | "custom_field_set" | "source"
    condition_value: Mapped[str] = mapped_column(String(200))
    points: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Territory(Base):
    """A named group of pincodes routed to one owning user/team -- the concrete shape behind
    "territory assignment": LeadRoutingRule's existing pincode trigger_type can reference a
    Territory by name instead of a single raw pincode, so an admin manages the pincode list once
    per territory rather than one routing rule per pincode.

    parent_territory_id (self-referential, same pattern as Company.parent_company_id) turns this
    into an arbitrary-depth tree -- zone -> state -> city -- for org-chart/rollup purposes only.
    Lead-routing pincode matching stays deliberately flat (a pincode matches the territory that
    directly lists it, not an ancestor's aggregated list) -- walking the tree on every routing
    evaluation would be real added complexity for a rollup that's about org structure, not
    matching logic."""
    __tablename__ = "territories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    pincodes: Mapped[list] = mapped_column(JSON, default=list)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    parent_territory_id: Mapped[str | None] = mapped_column(ForeignKey("territories.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SalesTarget(Base):
    """A revenue target for one user over one period -- "actual" isn't stored here, it's computed
    at read time from Σ Deal.value where owner_user_id/status="won"/closed within the period
    (services-level query), so a target never drifts out of sync with the deals that actually
    closed."""
    __tablename__ = "sales_targets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_value: Mapped[float] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomFieldDefinition(Base):
    """An admin-defined extra field rendered on the New/Edit forms for Lead/Deal/CrmContact/
    Customer and stored in that record's own custom_fields JSON column -- lets each tenant add
    whatever fields their business tracks (e.g. a payments CRM's "Product") without a code
    change. `name` doubles as the JSON key in custom_fields, so it must stay unique per
    (entity_id, applies_to)."""
    __tablename__ = "custom_field_definitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    applies_to: Mapped[str] = mapped_column(String(20))  # "lead" | "deal" | "crm_contact" | "customer"
    name: Mapped[str] = mapped_column(String(60))
    field_type: Mapped[str] = mapped_column(String(20), default="text")  # "text" | "number" | "date" | "dropdown"
    options: Mapped[list] = mapped_column(JSON, default=list)  # dropdown choices only
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attachment(Base):
    """A file attached to a Contact -- reuses services.save_upload, same extension-allowlist/
    size-cap/uuid-filename convention as every other upload in this app."""
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    uploaded_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(Base):
    """A converted, active tenant-of-the-tenant record (e.g. PAISAPE's own merchant) -- distinct
    from Textzi's own Organization/"Customers" admin list, which is Textzi's paying tenant, not
    the tenant's own customer. Reachable either from a Deal (deal_id set once a pipeline closes)
    or directly from a WhatsApp conversation (converted_from_conversation_id set, deal_id null) --
    both conversion paths land here."""
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    deal_id: Mapped[str | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    converted_from_conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """An in-app notification for one user -- lead/deal assigned, task assigned, quote awaiting
    approval, quote approved. Always created; a matching email additionally goes out via
    services.notify_user when CrmSettings.notify_email is on. SMS/WhatsApp delivery isn't wired
    yet -- both require a pre-registered DLT/template before any real send is possible, unlike
    plain transactional email, so CrmSettings.notify_sms/notify_whatsapp stay unused for now
    rather than faking a send."""
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    """A CRM follow-up/call/meeting reminder against a Contact -- the "log a call, schedule a
    follow-up" capability the earlier competitor gap-analysis found entirely missing. Deliberately
    contact_id-scoped (not lead_id/customer_id) since a task can predate either conversion (e.g. a
    reminder to follow up with a brand-new contact who isn't a lead yet). deal_id is optional --
    set when the task is tied to a specific in-progress opportunity, null for general contact
    follow-ups."""
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    deal_id: Mapped[str | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="follow_up")  # "call" | "meeting" | "follow_up" | "other"
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Only meaningful for type="meeting" -- gives the calendar view a real block to render instead
    # of a zero-length point in time. Null for calls/follow-ups, which are genuinely instantaneous.
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # "none" means one-off. A recurring task's due_at advances by this interval each time it's
    # marked done, rather than spawning a new row -- one task, a repeating due date.
    recurrence: Mapped[str] = mapped_column(String(10), default="none")  # "none" | "daily" | "weekly" | "monthly"
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # "low" | "normal" | "high"
    # Call disposition text -- only meaningful for type="call" (e.g. "no answer", "interested",
    # "call back later"); free text rather than an enum since dispositions are a sales-team
    # convention, not a platform one.
    outcome: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Quote(Base):
    """A GST-aware proforma quote tied to a Deal -- deliberately not an IRN-registered e-invoice
    (mandatory only above Rs 5 crore turnover, well past this product's SME target) so this stays
    a simple PDF-generation feature, not an Invoice Registration Portal integration. line_items is
    [{"description", "hsn_code", "quantity", "unit_price"}, ...]; CGST+SGST vs IGST is computed at
    send time from services.state_code_from_gstin (entity state vs the deal's own state), not
    stored, so a GSTIN correction before sending doesn't require editing stale stored tax lines."""
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"), index=True)
    quote_number: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    line_items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # "draft" | "sent" | "accepted" | "rejected"
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Light approval workflow -- a quote whose total exceeds CrmSettings.quote_approval_threshold
    # can't be sent until the creator's manager (User.manager_id) approves it. "not_required" for
    # anything under the threshold (or when no threshold is set), so this never gets in the way of
    # the common case.
    approval_status: Mapped[str] = mapped_column(String(20), default="not_required")  # "not_required" | "pending" | "approved" | "rejected"
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once "Convert to invoice" succeeds -- references invoices.id (Invoice lives in the
    # SMS-billing section of this same models.py, reused as-is rather than a parallel CRM invoice
    # table; a quote converts into exactly the same Invoice row type Textzi's own billing uses).
    converted_invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    # [{"user_id": str, "approved_at": iso str}, ...] -- one entry per approver in
    # CrmSettings.quote_approver_user_ids who has signed off. approval_status only flips to
    # "approved" once every configured approver has an entry here (see crm_quotes.approve_quote).
    approvals: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once the public /v1/public/quote/{id}/sign endpoint records an accept -- a lightweight
    # typed-name + timestamp + IP signature (not a cryptographic DocuSign-grade one), matching this
    # product's own SME-scope discipline elsewhere (e.g. Quote itself being a proforma, not an
    # IRN-registered e-invoice). status flips to "accepted"/"rejected" alongside these.
    signed_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Product(Base):
    """An entity's own price-list item -- the concrete shape behind "CPQ": a QuoteLineItem can
    optionally reference one (product_id) to pre-fill description/hsn_code/unit_price, but the
    line item itself always stores its own copy of those values (see Quote's own docstring on why
    tax lines aren't recomputed retroactively) -- a price change here never rewrites a quote
    that's already gone out. Deliberately no pricing-rule engine (volume discounts, bundles) --
    a flat price list is what an SME actually needs; revisit only if a real need shows up."""
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hsn_code: Mapped[str] = mapped_column(String(20), default="")
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentTemplate(Base):
    """A reusable document (proposal/contract/welcome letter/etc) with {{merge_field}} placeholders
    -- resolved against a Deal + its Contact/Company/entity at generation time (see crm_documents.
    _merge_fields) and rendered to a plain, paragraph-flow PDF (FPDF multi_cell over body split on
    blank lines) -- not a rich HTML-to-PDF renderer, which would need a new heavy dependency this
    codebase doesn't otherwise carry. Matches the same "simple PDF generation, not a document
    engine" scope already established for Quote's own PDF."""
    __tablename__ = "document_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    applies_to: Mapped[str] = mapped_column(String(20), default="proposal")  # "proposal" | "contract" | "other"
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedView(Base):
    """A user's own named filter preset for a CRM list page (Leads/Deals/Contacts) -- per-user,
    not shared, since "my untouched leads" means something different to every rep. filters mirrors
    whatever query-param shape that list page's own filter bar already uses, stored opaquely."""
    __tablename__ = "saved_views"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    applies_to: Mapped[str] = mapped_column(String(20))  # "lead" | "deal" | "crm_contact"
    name: Mapped[str] = mapped_column(String(80))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedReport(Base):
    """A user's own saved custom report definition -- object/group_by/measure/filters are plain
    strings validated against a small per-object whitelist at request time (crm.py's
    REPORT_FIELDS), never used to build raw SQL. Aggregation itself happens in Python over a
    normal ORM-filtered query, not a dynamic SQL GROUP BY -- simpler and safe by construction at
    the row counts an SME CRM actually has, and avoids needing a real query-builder engine."""
    __tablename__ = "saved_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    object_type: Mapped[str] = mapped_column(String(20))  # "deal" | "lead" | "task"
    group_by: Mapped[str] = mapped_column(String(40))
    measure: Mapped[str] = mapped_column(String(40))
    chart_type: Mapped[str] = mapped_column(String(20), default="bar")  # "bar" | "donut" | "table"
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    # None = not scheduled. "weekly" fires the runner's Monday pass; "monthly" fires its 1st-of-
    # month pass -- see crm.py's send_due_scheduled_reports (same daily-check-what's-due shape as
    # every other scheduled job in this codebase, not a per-report cron).
    schedule: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeadRoutingRule(Base):
    """Pincode/source/product-based auto-assignment for new leads -- a sibling of AutomationRule
    (same trigger->action shape) rather than an extension of it, since AutomationRule fires on
    inbound WhatsApp messages while this fires on lead creation, a genuinely different event with
    its own trigger vocabulary (pincode/source/product, not keyword/new_contact)."""
    __tablename__ = "lead_routing_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    trigger_type: Mapped[str] = mapped_column(String(20))  # "pincode" | "source" | "product" | "territory"
    trigger_value: Mapped[str] = mapped_column(String(200))
    assign_to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sequence(Base):
    """A named, ordered set of SequenceSteps a lead can be enrolled in -- a rule-based (not AI)
    multi-touch cadence, e.g. day 0 WhatsApp template, day 2 SMS, day 5 task reminder.

    exit_stage is the one branching primitive: once the enrolled deal reaches that stage (or is
    won/lost -- checked unconditionally, no flag needed), the runner stops sending further steps
    instead of blindly working through the rest of the cadence. Deliberately just one exit
    condition rather than a full branching graph -- covers the real case ("stop nurturing once
    they've moved forward or the deal's closed") without a process-designer UI."""
    __tablename__ = "sequences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    exit_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SequenceStep(Base):
    __tablename__ = "sequence_steps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id"), index=True)
    day_offset: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(20))  # "whatsapp_template" | "sms" | "task"
    # whatsapp_template: {"template_name", "template_language", "body_params"}; sms: {"template_id"
    # or "body"}; task: {"title", "type"} -- one flexible column, same reasoning as everywhere else
    # in this schema a message/step shape varies by type (ConversationMessage.payload etc).
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    # The one per-step branching primitive: if set, this step is skipped (but the enrollment still
    # advances past it) unless the deal is currently in this exact stage -- e.g. a day-3 "still
    # haven't heard back" nudge that only fires for deals still sitting in "inquiry", while deals
    # that already moved to "kyc" skip straight past it. Null (the default) always runs.
    only_if_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SequenceEnrollment(Base):
    """One deal's progress through one Sequence -- next_step_due_at is what the scheduled runner
    (crm_sequences.run_due_steps, called from the same daily-job hook archive_jobs.py already
    registers) scans for."""
    __tablename__ = "sequence_enrollments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id"), index=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"), index=True)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    next_step_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # "active" | "completed" | "stopped"
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


DEFAULT_CRM_PIPELINE_STAGES = [
    {"name": "inquiry", "probability": 10, "forecast_category": "pipeline"},
    {"name": "kyc", "probability": 30, "forecast_category": "pipeline"},
    {"name": "onboarding", "probability": 60, "forecast_category": "commit"},
    {"name": "live", "probability": 100, "forecast_category": "commit"},
    {"name": "renewal", "probability": 80, "forecast_category": "commit"},
]


class CrmSettings(Base):
    """One row per entity -- pipeline stage names and cross-channel notification toggles.
    notify_email is read by services.notify_user (fired on lead/deal assignment, deal won/lost,
    task assignment, quote approval events) to additionally email the recipient. notify_sms/
    notify_whatsapp stay unused -- neither can honestly deliver arbitrary notification text without
    a pre-registered DLT template (SMS) or approved message template (WhatsApp), so both are kept
    off the Notifications settings UI rather than wired to a fake/no-op send."""
    __tablename__ = "crm_settings"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    pipeline_stages: Mapped[list] = mapped_column(JSON, default=lambda: list(DEFAULT_CRM_PIPELINE_STAGES))
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Light quote-approval workflow (see Quote.approval_status) -- null means no threshold, every
    # quote sends without approval. Set to require sign-off above this INR amount.
    quote_approval_threshold: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Ordered list of User.id -- when a quote exceeds the threshold above, every user in this list
    # must approve (Quote.approvals) before the quote reaches approval_status="approved". Empty
    # list falls back to "anyone can approve", the original single-step behavior.
    quote_approver_user_ids: Mapped[list] = mapped_column(JSON, default=list)


class WebForm(Base):
    """One embeddable lead-capture form per entity -- deliberately singular (not a multi-form
    builder) matching SME scope: one "Contact us" form covers the common case, and the public
    submit endpoint (crm_public.py) is what actually creates the Contact+Lead, keyed by
    entity_id in the embed snippet's URL, not by a form id."""
    __tablename__ = "web_forms"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    fields: Mapped[list] = mapped_column(JSON, default=lambda: ["name", "email", "phone", "message"])
    success_message: Mapped[str] = mapped_column(String(300), default="Thanks! We'll be in touch shortly.")
    target_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipelines.id"), nullable=True)


class EmailAccount(Base):
    """One row per entity -- a tenant's own bring-your-own SMTP/IMAP mailbox, connected as a CRM
    channel (Textzi never operates this infrastructure or bills per message, unlike SMS/WhatsApp;
    it's a CRM-plan capability, gated the same way quotes/sequences are). Password fields store
    security.encrypt_secret(...) output, the same Fernet helper already used for the WABA App
    Secret and TOTP secrets -- no new crypto code."""
    __tablename__ = "email_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), unique=True, index=True)
    from_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    from_email: Mapped[str] = mapped_column(String(255))
    smtp_host: Mapped[str] = mapped_column(String(255))
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_username: Mapped[str] = mapped_column(String(255))
    smtp_password_encrypted: Mapped[str] = mapped_column(Text)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_username: Mapped[str] = mapped_column(String(255))
    imap_password_encrypted: Mapped[str] = mapped_column(Text)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="unverified")  # "unverified"|"connected"|"error"
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Segment(Base):
    """A saved contact filter -- AND semantics across both dimensions (a contact must have every
    listed label AND match every listed custom_attributes key=value pair). Kept intentionally
    simple (no OR/nested boolean logic) since that covers the real targeting need (campaigns,
    contact filtering) without the complexity of a full query builder."""
    __tablename__ = "segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    label_ids: Mapped[list] = mapped_column(JSON, default=list)
    custom_attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    """A bulk template send to a segment -- always a template (never free text), since Meta only
    allows business-initiated sends outside the 24h window via an approved template. Snapshots
    total_recipients/sent_count/failed_count as it runs rather than deriving them from
    CampaignRecipient on every read, so a large campaign's progress is a cheap read."""
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    template_name: Mapped[str] = mapped_column(String(512))
    template_language: Mapped[str] = mapped_column(String(20))
    body_params: Mapped[list] = mapped_column(JSON, default=list)
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|scheduled|sending|completed|failed
    total_recipients: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Null = send immediately via POST .../send (today's only path, unchanged). Set = the campaign
    # sits at status="scheduled" until run_due_campaigns (main.py's scheduler, same pattern as
    # CRM sequences/scheduled reports) picks it up and runs the exact same send logic.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CampaignRecipient(Base):
    __tablename__ = "campaign_recipients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|sent|failed|skipped_opted_out
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessHours(Base):
    """One row per entity. schedule is {"mon": {"open": "09:00", "close": "18:00"}, ...} -- a day
    key absent (or null) means closed that day. outside_hours_message, if set, is auto-sent (as a
    private-conversation reply, not a template -- see waba_automation.py) the first time a message
    arrives outside these hours."""
    __tablename__ = "business_hours"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    outside_hours_message: Mapped[str | None] = mapped_column(String(500), nullable=True)


class WebchatWidgetSettings(Base):
    """One row per entity -- the embeddable website chat widget's configuration. Gated on WABA OR
    CRM being active (either one, not both required -- confirmed with the user), so this lives in
    its own webchat.py module rather than under crm.py's _require_crm gate. widget_key is public
    (embedded directly in the customer's page source, not a secret) -- it identifies which
    entity's widget a given page load belongs to; allowed_origins is the real security boundary
    (see webchat_realtime.py's Origin-header check), since a WebSocket handshake isn't covered by
    the app's regular CORSMiddleware the way a normal HTTP request is."""
    __tablename__ = "webchat_widget_settings"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    widget_key: Mapped[str] = mapped_column(String(36), unique=True, default=uid)
    allowed_origins: Mapped[list] = mapped_column(JSON, default=list)
    bubble_color: Mapped[str] = mapped_column(String(20), default="#F1600D")
    greeting_message: Mapped[str] = mapped_column(String(300), default="Hi! How can we help?")
    offline_message: Mapped[str] = mapped_column(String(300), default="We're offline right now -- leave your email and we'll get back to you.")
    proactive_trigger_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # "time" (today's only behavior -- show after proactive_trigger_delay_seconds) or
    # "exit_intent" (show the moment the visitor's cursor leaves the top of the viewport, the
    # standard "about to close the tab" signal every proactive-chat product uses -- delay_seconds
    # is ignored for this type). Kept as one settings row with a type discriminator rather than
    # two separate trigger configs, since only one trigger fires per page load either way.
    proactive_trigger_type: Mapped[str] = mapped_column(String(20), default="time")
    proactive_trigger_delay_seconds: Mapped[int] = mapped_column(Integer, default=30)
    proactive_trigger_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Optional substring match against the visitor's current URL -- e.g. "/pricing" -- so a
    # proactive trigger only fires on pages it's actually relevant to (Freshchat's own "URL
    # targeting"). Empty/null means "every page", today's only behavior.
    proactive_url_pattern: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Freshdesk-style routing -- every new webchat conversation is auto-assigned to this group the
    # moment it's created (see webchat_public._find_or_create_webchat_conversation), reusing
    # TicketGroup as-is (already built for WhatsApp/email tickets, zero schema change needed there).
    default_group_id: Mapped[str | None] = mapped_column(ForeignKey("ticket_groups.id"), nullable=True)
    # Load-balanced assignment across the default group's own members -- off by default (group
    # routing alone, today's behavior, is enough for a lot of accounts). When on, a new
    # conversation is additionally auto-assigned (Conversation.assigned_user_id) to whichever group
    # member currently has the fewest open webchat conversations, rather than a round-robin
    # counter -- self-corrects for uneven agent workload instead of just cycling blindly, and
    # needs no extra state to track (a plain counter would drift after an agent goes offline/is
    # removed from the group, load-based doesn't have that failure mode).
    auto_assign_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class WebchatVisit(Base):
    """One row per anonymous website visitor session -- created on the widget's first /visit call
    on a page load, updated on subsequent page views within the same session. Telemetry is kept
    here rather than on Contact.custom_attributes because it's inherently per-visit (current page/
    referrer change every session), not a stable per-identity attribute -- cramming it into
    Contact would mean each new visit silently overwrites the last one's data. contact_id/
    conversation_id are set only once the visitor actually sends a message (see webchat_public.py)
    -- a visitor who loads the widget but never chats has a WebchatVisit row with no Contact at
    all, avoiding a flood of throwaway Contact rows from every page view."""
    __tablename__ = "webchat_visits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    current_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # [{"url": "...", "viewed_at": "..."}] -- appended to, not overwritten, across the same session.
    pages_viewed: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("entity_id", "visitor_id", name="uq_webchat_visits_entity_visitor_id"),
    )


class BookingLink(Base):
    """One row per entity -- a public "pick a slot" link (crm_public.py's /booking/{slug}
    endpoints). Available slots are computed from BusinessHours.schedule (this entity's existing
    weekly hours, already built for WhatsApp's own outside-hours auto-reply) minus any Task
    type="meeting" already occupying that window -- no separate schedule concept, no stored slot
    table. A booked slot becomes a normal Task, indistinguishable from one created by hand, so
    crm-tasks.vue's existing FullCalendar needs zero changes to show it."""
    __tablename__ = "booking_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SlaPolicy(Base):
    """One row per entity -- how many minutes a first reply, and separately a full resolution, are
    due within. Conversation.first_response_due_at/sla_breached and resolution_due_at/
    resolution_breached (see Conversation) track these per-conversation once set here; changing
    the policy only affects conversations started after the change."""
    __tablename__ = "sla_policies"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    first_response_minutes: Mapped[int] = mapped_column(Integer, default=60)
    resolution_minutes: Mapped[int] = mapped_column(Integer, default=480)


class Macro(Base):
    """A saved, manually-triggered bundle of actions run against one conversation in a single
    click -- distinct from AutomationRule (which fires automatically on a trigger). actions is an
    ordered list of {"type": "reply"|"label"|"status"|"assign", ...type-specific fields}, executed
    in order by waba_inbox.run_macro."""
    __tablename__ = "macros"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    actions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CsatSettings(Base):
    __tablename__ = "csat_settings"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class CsatResponse(Base):
    """One row per resolved conversation once CSAT is enabled -- created (rating null) the moment
    the rating request is sent, filled in when the customer taps one of the 1-5 quick-reply
    buttons (waba_webhooks.py matches the inbound button_reply against the newest unanswered row
    for that conversation)."""
    __tablename__ = "csat_responses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WabaWebhookSubscription(Base):
    """One outbound webhook URL per entity -- Textzi POSTs new-message and status-update events
    here as they happen, HMAC-signed the same way Meta signs its own webhooks to Textzi (see
    waba_webhooks.py's own signature check), so the customer's endpoint can verify authenticity."""
    __tablename__ = "waba_webhook_subscriptions"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WabaWebhookLog(Base):
    """One row per inbound call from Meta to /v1/webhooks/waba -- both the one-time GET verify
    handshake and every POST event delivery. Platform-admin-only visibility (mirrors ApiLog's
    "API Log & Report" for the SMS send API), built specifically so a connection/App-Review
    problem ("is Meta even calling us? did verification succeed? did we match a connection?") is
    answerable from the admin panel instead of grepping container logs. entity_id is nullable --
    unset whenever the phone_number_id in the payload doesn't match any connected WabaConnection,
    which is itself one of the failure modes this log exists to surface."""
    __tablename__ = "waba_webhook_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    direction: Mapped[str] = mapped_column(String(10))  # "verify" | "event"
    status: Mapped[str] = mapped_column(String(20))  # "ok" | "rejected" | "error"
    detail: Mapped[str] = mapped_column(String(300))
    phone_number_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class WabaApiCallLog(Base):
    """The outbound counterpart to WabaWebhookLog -- one row per call Textzi makes TO Meta's
    Graph API (sending a message, registering a phone number), not the inbound webhook direction.
    Exists because a send failure (e.g. Meta error 133010 "Account not registered") previously
    only surfaced as a one-off error banner in whichever dialog triggered it, with no durable
    record an admin could go back and check."""
    __tablename__ = "waba_api_call_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(30))  # "send_text" | "send_media" | "send_template" | "register"
    status: Mapped[str] = mapped_column(String(10))  # "ok" | "error"
    detail: Mapped[str] = mapped_column(String(300))
    to_wa_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
