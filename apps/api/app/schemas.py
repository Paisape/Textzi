from typing import Any, Literal
from pydantic import BaseModel, EmailStr, Field, field_validator
from .models import MessageCategory, Status, UserRole, UserStatus
from .security import assert_safe_webhook_url

# Shared by every field that accepts either a live 6-digit TOTP code or a recovery code
# (security.generate_recovery_code's "XXXXX-XXXXX" format, 11 chars with the dash, 10 without --
# callers normalize before hashing, so this pattern just needs to admit both shapes).
TWO_FACTOR_CODE_PATTERN = r"^[A-Za-z0-9-]{6,11}$"


class SmsSendRequest(BaseModel):
    """Dashboard Compose only (sms.py's compose_sms) -- a human filling out a form benefits from
    picking a template by its readable alias and letting Textzi fill in the variables live, with
    a preview. The external developer API (main.py) uses ApiSmsSendRequest instead: the caller's
    own system already has the complete message text, so there's nothing for Textzi to render."""
    # Must exactly match a Template.alias for this entity (services.resolve_template) --
    # unrestricted in format since alias itself is saved exactly as entered, normally the
    # DLT-portal-registered template name verbatim (e.g. "OTP NEW"), not a Textzi-imposed slug.
    template: str = Field(min_length=1, max_length=80)
    mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")
    variables: dict[str, str] = Field(default_factory=dict)


class SmsSendResponse(BaseModel):
    status: str
    message_id: str
    route: str
    balance: float
    credits_charged: int = 1


class ApiSmsSendResponse(BaseModel):
    """Same as SmsSendResponse minus route -- used as the response_model for every customer-facing
    send endpoint: the external API (main.py's send_sms/send_sms_via_url) and the dashboard's own
    Compose/Test feature (sms.py's compose_sms). The internal route/provider name never appears in
    a customer-facing response, even though the underlying send still builds a full
    SmsSendResponse internally (kept for Message.response_payload's admin-visible audit trail).
    Admin-only views (AdminMessageOut, MessageTelemetryOut) are separate schemas and still show
    route."""
    status: str
    message_id: str
    balance: float
    credits_charged: int = 1


class ApiSmsSendRequest(BaseModel):
    """POST /v1/sms/send -- template_id is your DLT-registered template id (not Textzi's own
    alias), and message is the complete, already-rendered text to send exactly as-is. Textzi
    does no interpolation here; DLT-pattern compliance for the final text is enforced by the
    carrier's own scrubbing, the same way it already is for the TTBS HTTP API directly."""
    template_id: str = Field(min_length=1, max_length=80)
    mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")
    message: str = Field(min_length=1, max_length=1600)


class BulkSmsRecipient(BaseModel):
    mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")
    message: str = Field(min_length=1, max_length=1600)


class BulkSmsSendRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=80)
    recipients: list[BulkSmsRecipient] = Field(min_length=1, max_length=100)


class BulkSmsRecipientResult(BaseModel):
    mobile: str
    status: str
    message_id: str | None
    credits_charged: int
    error: str | None


class BulkSmsSendResponse(BaseModel):
    accepted: int
    rejected: int
    balance: float
    results: list[BulkSmsRecipientResult]


class OptOutEntryOut(BaseModel):
    id: str
    mobile: str
    reason: str | None
    created_at: str


class OptOutEntryCreate(BaseModel):
    mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")
    reason: str | None = Field(default=None, max_length=200)


class PublicApiBaseUrlOut(BaseModel):
    api_base_url: str


class RoutePolicyRequest(BaseModel):
    # "entity" applies to every send from that whole account (matched by the caller's entity_id,
    # which api_key alone always resolves to) -- for a customer who wants all their sends on one
    # route without needing to pass user_id on every call. "user"/"group" stay for finer-grained
    # per-team-member routing when that's actually needed.
    subject_type: str = Field(pattern="^(group|user|entity)$")
    subject_id: str = Field(min_length=1, max_length=64)
    routes: list[str] = Field(min_length=1, max_length=5)


class EntityCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=2, max_length=160)


class PeCreate(BaseModel):
    value: str = Field(min_length=6, max_length=64)
    operator: str = Field(min_length=2, max_length=80)


class HeaderCreate(BaseModel):
    header_id: str = Field(min_length=2, max_length=64)
    value: str = Field(min_length=2, max_length=32)


class TemplateCreate(BaseModel):
    pe_id: str
    header_id: str
    # Saved exactly as entered (router trims whitespace only) -- normally the DLT-portal-
    # registered template name typed verbatim (e.g. "OTP NEW"), which SmsSendRequest.template
    # must match exactly at send time.
    alias: str = Field(min_length=1, max_length=200)
    dlt_template_id: str = Field(min_length=3, max_length=80)
    body: str = Field(min_length=1, max_length=1600)
    category: MessageCategory = MessageCategory.transactional


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    turnstile_token: str | None = None


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    next_step: str
    dev_email_code: str | None = None


class RegistrationStatusResponse(BaseModel):
    email_verified: bool
    mobile_verified: bool
    status: str


class VerifyEmailRequest(BaseModel):
    user_id: str
    code: str = Field(min_length=4, max_length=8)


class RequestMobileOtpRequest(BaseModel):
    user_id: str
    mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")


class RequestMobileOtpResponse(BaseModel):
    mobile: str
    next_step: str
    dev_mobile_code: str | None = None


class VerifyMobileRequest(BaseModel):
    user_id: str
    code: str = Field(min_length=4, max_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    turnstile_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    turnstile_token: str | None = None


class ForgotPasswordResponse(BaseModel):
    message: str
    # Present only in settings.environment == "development" -- mirrors the dev_email_code echo
    # pattern used everywhere else a code would otherwise only ever reach a real inbox.
    dev_code: str | None = None
    dev_user_id: str | None = None


class ResetPasswordRequest(BaseModel):
    user_id: str
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, max_length=128)
    # Required only if the account has 2FA enabled -- checked in auth.py's reset_password, not
    # here, since a blank .env-style "is this account 2FA-enabled" flag can't live in a request
    # schema. Accepts either a live TOTP code or a recovery code, same pattern as TWO_FACTOR_CODE_PATTERN.
    totp_code: str | None = Field(default=None, min_length=6, max_length=11, pattern=TWO_FACTOR_CODE_PATTERN)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class SessionOut(BaseModel):
    id: str
    ip_address: str | None
    user_agent: str | None
    created_at: str
    is_current: bool


class TwoFactorStatusOut(BaseModel):
    enabled: bool


class TwoFactorEnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorCodeRequest(BaseModel):
    # Accepts a recovery code too (not just a live TOTP code) -- confirm() only ever calls
    # _verify_totp_with_lockout directly so a recovery-code-shaped value there just fails as an
    # invalid TOTP code (correct: none exist yet before confirm succeeds); disable() and
    # step_up_2fa go through the combined check (auth.py's _verify_2fa_code) and accept either.
    code: str = Field(min_length=6, max_length=11, pattern=TWO_FACTOR_CODE_PATTERN)


class TwoFactorConfirmResponse(BaseModel):
    enabled: bool
    recovery_codes: list[str]


class TwoFactorRecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class Verify2faRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=11, pattern=TWO_FACTOR_CODE_PATTERN)


class TwoFactorAdminUpdate(BaseModel):
    enabled: bool


class UserProfile(BaseModel):
    id: str
    email: str
    full_name: str
    email_verified: bool
    mobile_verified: bool
    status: str
    organization_id: str | None = None
    role: str = "user"
    # None for a platform-staff account (no organization, this check never applies to them) or
    # for a tenant account that hasn't onboarded an organization yet (the pre-existing onboarding
    # gate handles that case first). True/False only once an organization exists -- the router
    # guard (apps/web) redirects to /complete-profile while this is False.
    profile_completed: bool | None = None


class OrganizationOnboardRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    entity_name: str | None = Field(default=None, max_length=160)
    # gstin stays optional -- the onboarding form lets a user declare "I don't have a GSTIN" and
    # skip it entirely; every other KYC/contact field below is mandatory for self-service
    # onboarding (unlike AdminCreateCustomerRequest, which keeps all of these optional since an
    # admin may be provisioning a customer before full KYC details are available).
    gstin: str | None = Field(default=None, min_length=15, max_length=15)
    # Required whenever gstin is blank (enforced in onboarding.py, not here, same convention as
    # the endpoint-level PAN regex check) -- when a GSTIN is given, its own prefix is authoritative
    # for GST state/place-of-supply and this is ignored.
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    pan: str = Field(min_length=10, max_length=10)
    industry: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=300)
    contact_person_name: str = Field(min_length=2, max_length=160)
    contact_email: EmailStr
    contact_mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")


class CompanyProfileOut(BaseModel):
    organization_id: str
    company_name: str
    pan: str | None
    gstin: str | None
    state_code: str | None
    address: str | None
    contact_email: str | None
    contact_mobile: str | None
    gst_certificate_uploaded: bool
    profile_completed: bool


class CompanyProfileUpdateResponse(BaseModel):
    profile_completed: bool


class OrganizationOnboardResponse(BaseModel):
    organization_id: str
    entity_id: str


class WalletTransactionOut(BaseModel):
    id: str
    type: str
    amount: float
    balance_after: float
    reference: str | None
    created_at: str


class WalletResponse(BaseModel):
    entity_id: str
    prepaid_balance: float
    credit_limit: float
    credit_used: float
    available_balance: float
    transactions: list[WalletTransactionOut]


class RechargeRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class RechargeResponse(BaseModel):
    entity_id: str
    amount: float
    available_balance: float
    credits_purchased: float | None = None
    gst_amount: float | None = None
    total_charged: float | None = None
    dev_note: str | None = None


class WalletTopupReportRowOut(BaseModel):
    order_id: str
    user_name: str | None
    user_email: str | None
    created_at: str
    ip_address: str | None
    rate_card_name: str | None
    amount: float
    gst_amount: float
    total_received: float
    credits_applied: float | None
    expected_credits: float | None
    mismatch: bool


class RazorpayOrderRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class RazorpayOrderResponse(BaseModel):
    order_id: str
    key_id: str
    amount_paise: int
    currency: str = "INR"


class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class UserAdminOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    status: str
    organization_id: str | None
    email_verified: bool
    mobile_verified: bool
    two_factor_enabled: bool = False


class AdminResetPasswordResponse(BaseModel):
    message: str
    dev_generated_password: str | None = None


class AdminResendVerificationResponse(BaseModel):
    message: str
    channel: str
    dev_code: str | None = None


class UserStatusUpdateRequest(BaseModel):
    status: UserStatus


class EntityStatusUpdateRequest(BaseModel):
    status: Status


class UserRoleUpdateRequest(BaseModel):
    role: UserRole


class AdminInviteUserRequest(BaseModel):
    email: EmailStr
    role: UserRole


class AdminCreateCustomerRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    entity_name: str | None = Field(default=None, max_length=160)
    gstin: str | None = Field(default=None, min_length=15, max_length=15)
    pan: str | None = Field(default=None, min_length=10, max_length=10)
    industry: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    contact_full_name: str = Field(min_length=2, max_length=160)
    contact_email: EmailStr
    contact_mobile: str | None = Field(default=None, max_length=20)


class AdminCreateCustomerResponse(BaseModel):
    organization_id: str
    entity_id: str
    user_id: str
    # Present only in settings.environment == "development" (no real email sender configured
    # yet) -- mirrors the dev_email_code/dev_invite_token echo pattern used everywhere else a
    # code or credential would otherwise only ever reach a real inbox.
    dev_email_code: str | None = None
    dev_generated_password: str | None = None


class TemplateSummary(BaseModel):
    id: str
    pe_id: str
    header_id: str
    alias: str
    dlt_template_id: str
    body: str
    category: str


class RateCardSlabIn(BaseModel):
    min_amount: float = Field(ge=0)
    max_amount: float | None = Field(default=None, ge=0)
    price_per_sms: float = Field(gt=0, le=100)


class RateCardSlabOut(RateCardSlabIn):
    id: str


class RateCardCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    channel: Literal["sms", "whatsapp"] = "sms"
    min_recharge_amount: float = Field(gt=0, le=1_000_000)
    slabs: list[RateCardSlabIn] = Field(min_length=1, max_length=20)


class RateCardSlabsReplace(BaseModel):
    slabs: list[RateCardSlabIn] = Field(min_length=1, max_length=20)


class RateCardMinRechargeUpdate(BaseModel):
    min_recharge_amount: float = Field(gt=0, le=1_000_000)


class RateCardPublicSettingsUpdate(BaseModel):
    show_on_public_pricing: bool
    public_tagline: str | None = Field(default=None, max_length=160)


class RateCardOut(BaseModel):
    id: str
    name: str
    channel: str
    is_default: bool
    min_recharge_amount: float
    show_on_public_pricing: bool
    public_tagline: str | None
    slabs: list[RateCardSlabOut]


class RateCardAssignmentRequest(BaseModel):
    user_id: str
    rate_card_id: str


class RateCardAssignmentOut(BaseModel):
    user_id: str
    user_email: str
    rate_card_id: str
    rate_card_name: str


class WalletQuoteRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class WalletQuoteResponse(BaseModel):
    amount: float
    gst_amount: float
    total_amount: float
    credits: float
    price_per_sms: float
    rate_card_name: str
    min_recharge_amount: float


class RateCardSummary(BaseModel):
    name: str
    min_recharge_amount: float
    slabs: list[RateCardSlabOut]


class PublicRateCardOut(RateCardSummary):
    channel: str
    public_tagline: str | None = None


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=20)
    company: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=4000)
    turnstile_token: str | None = None


class ContactResponse(BaseModel):
    message: str


class ContactMessageAdminOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None
    company: str | None
    message: str
    email_sent: bool
    created_at: str


def _not_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


class TestimonialSubmitRequest(BaseModel):
    author_name: str = Field(min_length=1, max_length=120)
    author_role: str = Field(min_length=1, max_length=160)
    quote: str = Field(min_length=1, max_length=600)

    # min_length=1 alone lets a whitespace-only string (e.g. a single space) through, which then
    # renders as a visually blank testimonial card -- strip and reject anything blank after that.
    _validate_not_blank = field_validator("author_name", "author_role", "quote")(_not_blank)


class TestimonialOut(BaseModel):
    id: str
    author_name: str
    author_role: str
    quote: str
    status: str
    created_at: str


class TestimonialAdminOut(BaseModel):
    id: str
    organization_name: str | None
    submitted_by_email: str | None
    author_name: str
    author_role: str
    quote: str
    status: str
    created_at: str
    reviewed_at: str | None
    reviewed_by: str | None


class TestimonialAdminCreateRequest(BaseModel):
    author_name: str = Field(min_length=1, max_length=120)
    author_role: str = Field(min_length=1, max_length=160)
    quote: str = Field(min_length=1, max_length=600)

    _validate_not_blank = field_validator("author_name", "author_role", "quote")(_not_blank)


class TestimonialStatusUpdateRequest(BaseModel):
    status: Literal["approved", "rejected"]


class PublicTestimonialOut(BaseModel):
    author_name: str
    author_role: str
    quote: str


class TrackVisitRequest(BaseModel):
    session_id: str | None = None
    path: str
    referrer: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None


class TrackVisitResponse(BaseModel):
    session_id: str


class VisitorSessionAdminOut(BaseModel):
    id: str
    user_id: str | None
    user_email: str | None
    country: str | None
    browser: str | None
    os: str | None
    device_type: str | None
    first_referrer: str | None
    first_seen: str
    last_seen: str
    page_view_count: int


class AnalyticsSummaryOut(BaseModel):
    total_sessions: int
    total_page_views: int
    sessions_last_7_days: int
    top_pages: list[dict]
    top_countries: list[dict]
    top_referrers: list[dict]
    device_breakdown: list[dict]


class MessageOut(BaseModel):
    id: str
    recipient: str
    rendered_body: str
    status: str
    credits_charged: int = 1
    created_at: str


class ChannelStatusResponse(BaseModel):
    subscription_price: float
    subscription_paid: bool
    dlt_status: str = Field(description="not_started | pending_review | approved")
    channel_active: bool


class ChannelSettingsOut(BaseModel):
    encryption_enabled: bool
    dr_webhook_url: str | None = None


class ChannelSettingsUpdate(BaseModel):
    encryption_enabled: bool
    dr_webhook_url: str | None = Field(default=None, max_length=500)

    @field_validator("dr_webhook_url")
    @classmethod
    def _validate_webhook_url(cls, value: str | None) -> str | None:
        if value:
            assert_safe_webhook_url(value)
        return value


class TtbsDrWebhookPayload(BaseModel):
    """TTBS's own DR callback body -- field names/casing exactly as documented (PascalCase,
    not Textzi's usual snake_case), since we don't control what they send."""
    DRType: str | None = None
    SubmissionID: str
    Recipient: str | None = None
    DeliveryStatusCode: int
    DeliveryStatus: str | None = None
    DeliveryTimestamp: str | None = None


class DeliveryStatusCodeRuleCreate(BaseModel):
    code: int = Field(ge=0, le=999)
    label: str | None = Field(default=None, max_length=160)
    refund: bool = True


class DeliveryStatusCodeRuleOut(BaseModel):
    code: int
    label: str | None
    refund: bool


class TtbsWebhookInfoOut(BaseModel):
    webhook_url: str | None
    configured: bool


class ChannelFeeConfigOut(BaseModel):
    channel: str
    subscription_price: float
    dlt_platform_fee: float
    dlt_service_fee: float


class ApiKeyOut(BaseModel):
    id: str
    active: bool
    allowed_ips: list[str]


class ApiKeyCreateRequest(BaseModel):
    otp_code: str = Field(min_length=4, max_length=8)


class ApiKeyCreateResponse(BaseModel):
    id: str
    api_key: str
    warning: str = "Store this key securely; it will not be shown again."


class ApiKeyIpWhitelistUpdate(BaseModel):
    allowed_ips: list[str] = Field(max_length=50)
    otp_code: str = Field(min_length=4, max_length=8)


class ApiKeyRevokeRequest(BaseModel):
    otp_code: str = Field(min_length=4, max_length=8)


class ApiKeyOtpRequest(BaseModel):
    action: Literal["generate_key", "update_ip_whitelist", "revoke_key"]


class ApiKeyOtpResponse(BaseModel):
    sent_via: Literal["mobile", "email"]
    masked_destination: str
    dev_otp_code: str | None = None


class ReportsSummaryResponse(BaseModel):
    total: int
    submitted: int
    failed: int
    accepted: int


class ChannelFeeConfigUpdate(BaseModel):
    subscription_price: float = Field(ge=0, le=1_000_000)
    dlt_platform_fee: float = Field(ge=0, le=1_000_000)
    dlt_service_fee: float = Field(ge=0, le=1_000_000)


class DltRequestQuoteResponse(BaseModel):
    combined_fee: float
    gst_amount: float
    total_amount: float
    telemarketer_name: str
    telemarketer_id: str


class DltDocumentOut(BaseModel):
    id: str
    filename: str
    document_type: str


class DltOnboardingRequestOut(BaseModel):
    id: str
    status: str
    notes: str | None
    company_name: str | None
    company_pan: str | None
    company_gst: str | None
    authorized_signatory_name: str | None
    contact_number: str | None
    contact_email: str | None
    authorized_person_aadhar_masked: str | None
    total_amount: float
    created_at: str
    documents: list[DltDocumentOut]


class DltOnboardingRequestAdminOut(DltOnboardingRequestOut):
    entity_id: str
    entity_name: str
    organization_name: str


class DltOnboardingRequestStatusUpdate(BaseModel):
    status: str = Field(pattern="^(in_progress|completed|rejected)$")


class InvoiceOut(BaseModel):
    id: str
    entity_id: str
    invoice_number: str | None
    type: str
    status: str
    base_amount: float
    gst_amount: float
    total_amount: float
    reference: str | None
    notes: str | None
    created_at: str
    issued_at: str | None


class InvoiceAdminOut(InvoiceOut):
    entity_name: str
    organization_name: str
    # Zoho reconciliation status -- not exposed on the customer-facing InvoiceOut this extends,
    # since it's purely an internal accounting-sync concern. organization_zoho_linked distinguishes
    # "never attempted because the org isn't linked yet" from "linked, but not pushed/failed" --
    # both leave zoho_sync_status="pending"/"failed" the same way, so the linked flag is what lets
    # the admin UI tell those apart.
    organization_zoho_linked: bool
    zoho_sync_status: str
    zoho_invoice_id: str | None
    zoho_payment_id: str | None
    zoho_mark_paid: bool
    zoho_sync_error: str | None


class WalletLedgerEntryOut(BaseModel):
    id: str
    channel: str
    type: str
    amount: float
    balance_before: float
    balance_after: float
    reference: str | None
    created_at: str


class PaymentLedgerEntryOut(BaseModel):
    id: str
    provider: str
    provider_order_id: str
    purpose: str
    amount: float
    status: str
    created_at: str


class PurchaseLedgerEntryOut(BaseModel):
    id: str
    invoice_number: str | None
    base_amount: float
    gst_amount: float
    total_amount: float
    credits_purchased: float | None
    price_per_sms: float | None
    created_at: str


class ActivityLogEntryOut(BaseModel):
    id: str
    event_type: str
    description: str
    actor_email: str
    ip_address: str | None
    user_agent: str | None
    created_at: str


class AdminAuditLogEntryOut(BaseModel):
    id: str
    event_type: str
    description: str
    actor_email: str
    ip_address: str | None
    user_agent: str | None
    organization_name: str | None
    created_at: str


class AdminMessageOut(BaseModel):
    """A customer's message, viewed cross-org by an admin. Masking follows the message's own
    is_encrypted flag -- same rule the customer's own Logs tab uses -- so admins never see more
    than the customer themselves chose to expose."""
    id: str
    organization_name: str | None
    entity_name: str
    recipient: str
    rendered_body: str
    status: str
    route: str | None
    credits_charged: int
    delivery_status_code: int | None
    delivery_status_description: str | None
    delivery_status_text: str | None
    delivery_error: str | None
    created_at: str


class AdminPlatformMessageOut(BaseModel):
    """The platform's own SMS log (currently just login-OTP sends) -- entirely separate from
    tenant messages."""
    id: str
    purpose: str
    recipient: str
    rendered_body: str
    status: str
    route: str | None
    delivery_status_code: int | None
    delivery_status_description: str | None
    delivery_status_text: str | None
    created_at: str


class DeliveryAttemptTelemetryOut(BaseModel):
    id: str
    route: str
    status: str
    provider_message_id: str | None
    error: str | None
    delivery_status_code: int | None
    delivery_status_description: str | None
    delivery_status_text: str | None
    delivered_at: str | None
    request_payload: dict[str, Any] | None
    response_body: str | None
    webhook_payload: dict[str, Any] | None
    customer_webhook_url: str | None
    customer_webhook_payload: dict[str, Any] | None
    customer_webhook_status: str | None
    customer_webhook_error: str | None
    customer_webhook_sent_at: str | None
    created_at: str


class MessageTelemetryOut(BaseModel):
    message_id: str
    recipient: str
    rendered_body: str
    status: str
    request_payload: dict[str, Any] | None
    response_payload: dict[str, Any] | None
    created_at: str
    attempts: list[DeliveryAttemptTelemetryOut]


class PlatformMessageTelemetryOut(BaseModel):
    message_id: str
    purpose: str
    recipient: str
    rendered_body: str
    status: str
    route: str | None
    request_payload: dict[str, Any] | None
    response_body: str | None
    delivery_status_code: int | None
    delivery_status_description: str | None
    delivery_status_text: str | None
    delivered_at: str | None
    webhook_payload: dict[str, Any] | None
    created_at: str


class NotificationOut(BaseModel):
    id: str
    severity: str
    title: str
    description: str
    link: str | None = None


class ApiLogEntryOut(BaseModel):
    id: str
    endpoint: str
    method: str | None
    status_code: int
    latency_ms: int
    error: str | None
    created_at: str


class AdminApiLogOut(BaseModel):
    id: str
    entity_id: str | None
    entity_name: str | None
    organization_name: str | None
    message_id: str | None
    endpoint: str
    method: str | None
    status_code: int
    latency_ms: int
    error: str | None
    ip_address: str | None
    country: str | None
    user_agent: str | None
    created_at: str


class WalletCreditRequest(BaseModel):
    entity_id: str
    amount: float = Field(gt=0, le=1_000_000)
    # False (default) leaves the invoice as a draft requiring admin Approve/Reject review before
    # it can ever reach Zoho -- true skips that review and issues (and Zoho-syncs) immediately, for
    # when the admin already knows this credit is legitimate and doesn't need a second look.
    generate_invoice: bool = False
    # Every other invoice type (wallet_recharge, dlt_fee, channel_subscription) is only ever
    # created after a payment is already confirmed one way or another, so those always reconcile
    # as paid in Zoho Books. An admin manual credit is the one case with no such guarantee -- it
    # could be a real bank transfer collected outside Razorpay, or a free/promotional credit with
    # no money changing hands -- so the admin decides explicitly per credit.
    paid: bool = True
    notes: str | None = Field(default=None, max_length=300)


class WalletDebitRequest(BaseModel):
    entity_id: str
    amount: float = Field(gt=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=300)


class WalletDebitResponse(BaseModel):
    entity_id: str
    credits_debited: float
    available_balance: float


class EntityWalletSummaryOut(BaseModel):
    entity_id: str
    prepaid_balance: float
    credit_limit: float
    credit_used: float
    available_balance: float


class WalletAdjustmentQuoteOut(BaseModel):
    credits: float
    price_per_sms: float


class WalletCreditResponse(BaseModel):
    entity_id: str
    credits_added: float
    available_balance: float
    invoice: InvoiceOut | None = None


class PaymentOrderAdminOut(BaseModel):
    id: str
    entity_id: str
    entity_name: str
    organization_name: str
    provider: str
    provider_order_id: str
    amount: float
    purpose: str
    status: str
    created_at: str


class PaymentOrderReconcileResponse(BaseModel):
    our_status_before: str
    razorpay_status: str
    action_taken: str


class WalletTopupReportRowOut(BaseModel):
    order_id: str
    user_name: str | None
    user_email: str | None
    created_at: str
    ip_address: str | None
    rate_card_name: str | None
    amount: float
    gst_amount: float
    total_received: float
    expected_credits: float | None
    credits_applied: float | None
    mismatch: bool
    account_status: str | None


class PlatformSmsSettingsOut(BaseModel):
    pe_id: str | None
    pe_operator: str | None
    header_id: str | None
    sender_id: str | None
    dlt_template_id: str | None
    template_body: str | None
    route: str | None


class PlatformSmsSettingsUpdate(BaseModel):
    pe_id: str | None = None
    pe_operator: str | None = None
    header_id: str | None = None
    sender_id: str | None = None
    dlt_template_id: str | None = None
    template_body: str | None = None
    route: str | None = None


class PlatformSmtpSettingsOut(BaseModel):
    host: str | None
    port: int
    username: str | None
    from_address: str
    use_tls: bool
    configured: bool


class PlatformSmtpSettingsUpdate(BaseModel):
    host: str | None = None
    port: int = Field(default=587, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    from_address: str = "no-reply@textzi.in"
    use_tls: bool = True


class PlatformR2SettingsOut(BaseModel):
    account_id: str | None
    access_key_id: str | None
    bucket_name: str | None
    configured: bool


class PlatformR2SettingsUpdate(BaseModel):
    account_id: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None  # blank = keep the existing one, same convention as SMTP's password
    bucket_name: str | None = None


class PlatformTurnstileSettingsOut(BaseModel):
    site_key: str | None
    configured: bool


class PlatformTurnstileSettingsUpdate(BaseModel):
    site_key: str | None = None
    secret_key: str | None = None  # blank = keep the existing one, same convention as SMTP's password / R2's secret_access_key


class TurnstileTestConnectionResponse(BaseModel):
    ok: bool
    detail: str


class PublicTurnstileConfigOut(BaseModel):
    site_key: str


class PlatformZohoSettingsOut(BaseModel):
    client_id: str | None
    accounts_domain: str | None
    api_domain: str | None
    organization_id: str | None
    gst_tax_id_intrastate: str | None
    gst_tax_id_interstate: str | None
    gst_tax_id_zero_rated: str | None
    payment_deposit_account_id: str | None
    item_code_sms_service: str | None
    item_code_platform_fee_dlt: str | None
    item_code_platform_fee_whatsapp: str | None
    configured: bool
    connected: bool


class PlatformZohoSettingsUpdate(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None  # blank = keep the existing one, same convention as SMTP's password
    accounts_domain: str | None = None
    organization_id: str | None = None
    gst_tax_id_intrastate: str | None = None
    gst_tax_id_interstate: str | None = None
    gst_tax_id_zero_rated: str | None = None
    payment_deposit_account_id: str | None = None
    item_code_sms_service: str | None = None
    item_code_platform_fee_dlt: str | None = None
    item_code_platform_fee_whatsapp: str | None = None


class ZohoConnectRequest(BaseModel):
    grant_code: str


class ZohoRetryResponse(BaseModel):
    invoice_id: str
    zoho_sync_status: str
    zoho_invoice_id: str | None
    zoho_sync_error: str | None


class ZohoOrganizationLinkResponse(BaseModel):
    organization_id: str
    zoho_contact_id: str


class ZohoAccountOut(BaseModel):
    account_id: str
    account_name: str
    account_type: str


class ZohoTaxRateOut(BaseModel):
    tax_id: str
    tax_name: str
    tax_percentage: float | None = None


class ZohoCallLogOut(BaseModel):
    id: str
    invoice_id: str | None
    invoice_number: str | None
    method: str
    path: str
    status: str
    status_code: int | None
    error: str | None
    created_at: str


class ArchiveRunLogOut(BaseModel):
    id: str
    job: str
    status: str
    records_processed: int
    error: str | None
    started_at: str
    finished_at: str


class ArchiveManifestOut(BaseModel):
    id: str
    tier: str
    period: str
    record_count: int
    size_bytes: int
    created_at: str


class ArchiveRunNowResponse(BaseModel):
    local: dict
    r2: dict


class R2TestConnectionResponse(BaseModel):
    ok: bool
    detail: str


class PlatformGeneralSettingsOut(BaseModel):
    company_name: str
    company_address: str
    company_gstin: str
    company_state: str
    company_state_code: str
    company_phone: str
    support_email: str
    public_api_base_url: str


class PlatformGeneralSettingsUpdate(BaseModel):
    company_name: str | None = None
    company_address: str | None = None
    company_gstin: str | None = None
    company_state: str | None = None
    company_state_code: str | None = None
    company_phone: str | None = None
    support_email: str | None = None
    public_api_base_url: str | None = None


class PublicCompanyInfoOut(BaseModel):
    company_name: str
    company_address: str
    company_phone: str
    support_email: str


class PlatformWalletTransactionOut(BaseModel):
    id: str
    type: str
    amount: float
    balance_after: float
    reference: str | None
    created_at: str


class PlatformWalletOut(BaseModel):
    balance: float
    transactions: list[PlatformWalletTransactionOut]


class PlatformWalletTopupRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    notes: str | None = None


class PlatformTestSmsRequest(BaseModel):
    recipient: str = Field(min_length=6, max_length=20)


class PlatformTestSmsResponse(BaseModel):
    message_id: str
    status: str
    recipient: str


class TeamInviteRequest(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.sub_user


class TeamInviteResponse(BaseModel):
    invitation_id: str
    email: str
    dev_invite_token: str | None = None


class TeamMemberOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    status: str


class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=8, max_length=128)
    mobile: str | None = Field(default=None, max_length=20)


class PermissionsResponse(BaseModel):
    capabilities: list[str]


class UsageOrgBreakdown(BaseModel):
    organization_id: str
    organization_name: str
    entity_count: int
    messages_sent: int
    wallet_balance: float
    last_activity: str | None


class UsageSummaryResponse(BaseModel):
    total_organizations: int
    total_entities: int
    total_messages_sent: int
    total_wallet_credits_issued: float
    total_revenue: float
    breakdown: list[UsageOrgBreakdown]


class CustomerAdminOut(BaseModel):
    organization_id: str
    organization_name: str
    primary_contact_name: str | None
    primary_contact_email: str | None
    primary_contact_mobile: str | None
    entity_count: int
    wallet_balance: float
    messages_sent: int
    last_activity: str | None


class CustomerDeleteResponse(BaseModel):
    deleted: bool
    organization_id: str
    organization_name: str


class HeaderAdminOut(BaseModel):
    id: str
    header_id: str
    value: str
    status: str


class PeIdAdminOut(BaseModel):
    id: str
    value: str
    operator: str
    status: str
    headers: list[HeaderAdminOut]


class TemplateAdminDetailOut(BaseModel):
    id: str
    alias: str
    dlt_template_id: str
    category: str
    status: str


class EntityAdminDetailOut(BaseModel):
    id: str
    name: str
    status: str
    pe_ids: list[PeIdAdminOut]
    templates: list[TemplateAdminDetailOut]


class RechargeDetailOut(BaseModel):
    id: str
    type: str
    amount: float
    reference: str | None
    created_at: str


class PaymentDetailOut(BaseModel):
    id: str
    provider: str
    provider_order_id: str
    amount: float
    status: str
    created_at: str


class OrganizationOverviewResponse(BaseModel):
    organization_id: str
    organization_name: str
    gstin: str | None
    pan: str | None
    industry: str | None
    address: str | None
    zoho_contact_id: str | None
    created_at: str
    entities: list[EntityAdminDetailOut]
    wallet_balance: float
    messages_sent: int
    total_recharged: float
    primary_contact_name: str | None
    primary_contact_email: str | None
    primary_contact_mobile: str | None
    primary_contact_two_factor_enabled: bool
    users: list[TeamMemberOut]
    invoices: list[InvoiceOut]
    recharges: list[RechargeDetailOut]
    payments: list[PaymentDetailOut]
