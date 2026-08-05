import enum
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
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
    # ERPNext's Customer doctype name (its own primary key, not a Textzi id) -- set the first time
    # any invoice for this organization is pushed to ERPNext (services.erpnext.ensure_customer);
    # every later invoice reuses it instead of creating a duplicate Customer record.
    erpnext_customer_name: Mapped[str | None] = mapped_column(String(140), nullable=True)


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
    provider: Mapped[str] = mapped_column(String(20))
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
    # Best-effort push to the customer's self-hosted ERPNext (services.erpnext) -- never blocks
    # or fails issue_invoice itself over an ERPNext-side problem. "pending" until the first sync
    # attempt (or forever, if ERPNext isn't configured at all); "failed" keeps erpnext_sync_error
    # around so an admin can see why without digging through logs.
    erpnext_invoice_name: Mapped[str | None] = mapped_column(String(140), nullable=True)
    erpnext_sync_status: Mapped[str] = mapped_column(String(20), default="pending")
    erpnext_sync_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Decided once at creation time (not re-derived on every sync/retry, so a retry always
    # reconciles the same way it originally would have): wallet_recharge/dlt_fee/channel_subscription
    # are only ever created after a payment is already confirmed one way or another, so they default
    # True; admin_credit is the one case where the admin themselves picks Paid or Unpaid (see
    # WalletCreditRequest.paid). True creates a matching ERPNext Payment Entry, reconciled against
    # the Sales Invoice, right after it's submitted -- erpnext_payment_entry_name tracks it the same
    # way erpnext_invoice_name tracks the invoice, so a retry never creates a duplicate.
    erpnext_mark_paid: Mapped[bool] = mapped_column(Boolean, default=True)
    erpnext_payment_entry_name: Mapped[str | None] = mapped_column(String(140), nullable=True)


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
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelSubscription(Base):
    """Whether an entity has paid the (admin-set) one-time activation price for a channel.
    `paid_at` NULL means unpaid. When the channel's ChannelFeeConfig.subscription_price is 0,
    services.channel_active() treats this condition as automatically satisfied without
    requiring a row here at all."""
    __tablename__ = "channel_subscriptions"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(10), primary_key=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    summed and shown to customers as one combined figure -- never itemised to them."""
    __tablename__ = "channel_fee_configs"
    channel: Mapped[str] = mapped_column(String(10), primary_key=True)
    subscription_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    dlt_platform_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    dlt_service_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("entity_id", "idempotency_key", name="uq_message_idempotency"),)


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


class PlatformErpNextSettings(Base):
    """Singleton row. Connection details for the customer's self-hosted ERPNext (Frappe) instance
    -- ERPNext is the source of truth for the invoice DOCUMENT itself (services.erpnext creates
    the Customer/Item/Sales Invoice there and fetches the rendered PDF back); Textzi's own fpdf2
    rendering (invoicing.py) only ever runs as a fallback when ERPNext is unconfigured or a call
    fails, so a customer is never left with literally no invoice while a failure is retried. The
    item_code_* fields map each of Textzi's own Invoice.type values to an ERPNext Item code --
    auto-created there the first time it's needed if it doesn't already exist. gst_tax_template
    names a real, pre-configured ERPNext "Sales Taxes and Charges Template" (e.g. "Output GST
    In-state - PTPL") -- confirmed live that referencing one by name is all a Sales Invoice needs
    for ERPNext to compute and post the correct CGST/SGST lines itself, so Textzi never needs to
    know the underlying account heads at all."""
    __tablename__ = "platform_erpnext_settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="platform")
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_secret_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    gst_tax_template: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # The ERPNext Bank/Cash account a reconciling Payment Entry deposits into (its "Paid To") --
    # required before any invoice marked erpnext_mark_paid=True can actually sync; picked by the
    # admin from a real fetched list (GET .../erpnext-accounts), not free text, since it must be a
    # real leaf (non-group) account.
    payment_account: Mapped[str | None] = mapped_column(String(160), nullable=True)
    print_format: Mapped[str | None] = mapped_column(String(140), nullable=True)
    # Optional -- confirmed live (DocType metadata: reqd=0, and a real Customer create succeeded
    # with neither field set at all) that ERPNext doesn't require this. Kept as an admin choice
    # purely for ERPNext-side reporting/segmentation; blank means every Customer Textzi creates
    # just has no group set, which ERPNext is fine with. Territory was the same story but with no
    # actual reporting upside identified, so it was dropped entirely rather than kept blank-by-default.
    customer_group: Mapped[str | None] = mapped_column(String(140), nullable=True)
    # None = let ERPNext use its own configured default Sales Invoice naming series. Only needs
    # setting when that default produces a name longer than 16 characters -- confirmed live that
    # india_compliance (GST) rejects invoice creation outright above that length ("Transaction Name
    # must be 16 characters or fewer to meet GST requirements"), which a verbose default series
    # like "ACC-SINV-.YYYY.-" (well over 16 once the running number is appended) will always hit.
    sales_invoice_naming_series: Mapped[str | None] = mapped_column(String(40), nullable=True)
    item_code_wallet_recharge: Mapped[str | None] = mapped_column(String(140), nullable=True)
    item_code_dlt_fee: Mapped[str | None] = mapped_column(String(140), nullable=True)
    item_code_channel_subscription: Mapped[str | None] = mapped_column(String(140), nullable=True)
    item_code_admin_credit: Mapped[str | None] = mapped_column(String(140), nullable=True)


class ErpNextApiCallLog(Base):
    """Every ERPNext API call Textzi makes, success or failure -- the admin-visible history that
    lets an admin see exactly what happened and why before retrying (services.erpnext logs one
    row per HTTP call, not one per invoice, so a single invoice's Customer + Item + Sales
    Invoice + PDF-fetch chain shows as its own timeline of attempts)."""
    __tablename__ = "erpnext_api_call_logs"
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
