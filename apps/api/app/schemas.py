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
    mobile: str | None = None
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
    # null = full access to whatever channels the org has active; "sms"|"waba"|"crm" locks this
    # teammate to that one channel's focused workspace (see the router guard in apps/web).
    channel_scope: str | None = None
    # Only meaningful alongside channel_scope -- null means every page in that channel, a list
    # narrows to just those route names (see the router guard in apps/web).
    page_scope: list[str] | None = None


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
    dev_recharge_available: bool


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


class BillingPlanOut(BaseModel):
    id: str
    channel: str
    name: str
    period: str
    price: float
    message_limit: int | None
    user_limit: int | None
    active: bool


class BillingPlanCreateRequest(BaseModel):
    channel: str = Field(pattern="^(waba|crm)$")
    name: str = Field(min_length=1, max_length=80)
    period: str = Field(pattern="^(monthly|quarterly|yearly)$")
    price: float = Field(gt=0, le=1_000_000)
    message_limit: int | None = Field(default=None, gt=0)
    user_limit: int | None = Field(default=None, gt=0)
    active: bool = True


class ChannelSubscriptionStatusOut(BaseModel):
    channel: str
    plan: BillingPlanOut | None
    period_start: str | None
    period_end: str | None
    messages_used: int
    seats_used: int


class PlanOrderRequest(BaseModel):
    plan_id: str


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
    dev_recharge_available: bool


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
    enabled: bool


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
    enabled: bool = True


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


class ProfileChangeRequestCreate(BaseModel):
    requested_full_name: str | None = Field(default=None, min_length=2, max_length=160)
    requested_email: EmailStr | None = None
    requested_mobile: str | None = Field(default=None, pattern=r"^[1-9][0-9]{9,14}$")
    requested_company_name: str | None = Field(default=None, min_length=2, max_length=160)
    requested_gstin: str | None = Field(default=None, min_length=15, max_length=15)
    requested_pan: str | None = Field(default=None, min_length=10, max_length=10)
    requested_address: str | None = Field(default=None, min_length=1, max_length=300)
    requested_state_code: str | None = Field(default=None, min_length=2, max_length=2)
    customer_note: str | None = Field(default=None, max_length=1000)

    @field_validator("requested_email", mode="before")
    @classmethod
    def _blank_email_is_none(cls, v):
        # EmailStr rejects "" outright -- an empty string here just means "not requesting this
        # field changed", same as every other requested_* field being omitted/null.
        return v or None


class ProfileChangeRequestOut(BaseModel):
    id: str
    status: str
    requested_full_name: str | None
    requested_email: str | None
    requested_mobile: str | None
    requested_company_name: str | None
    requested_gstin: str | None
    requested_pan: str | None
    requested_address: str | None
    requested_state_code: str | None
    customer_note: str | None
    admin_note: str | None
    created_at: str
    reviewed_at: str | None


class ProfileChangeRequestAdminOut(ProfileChangeRequestOut):
    user_id: str
    user_email: str
    user_full_name: str


class ProfileChangeRequestStatusUpdate(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    admin_note: str | None = Field(default=None, max_length=1000)


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


class SmsVolumeDay(BaseModel):
    date: str  # "YYYY-MM-DD"
    sent: int
    delivered: int
    failed: int


class SmsFailureReason(BaseModel):
    reason: str
    count: int


class SmsAnalyticsOut(BaseModel):
    total_sent: int
    delivered_count: int
    failed_count: int
    pending_count: int
    delivery_rate: float | None  # delivered / (delivered + failed), null if neither happened yet
    failure_reasons: list[SmsFailureReason]
    volume_by_day: list[SmsVolumeDay]


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


class AdminAlertOut(BaseModel):
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


class AdminWabaWebhookLogOut(BaseModel):
    id: str
    direction: str
    status: str
    detail: str
    phone_number_id: str | None
    entity_id: str | None
    entity_name: str | None
    organization_name: str | None
    ip_address: str | None
    created_at: str


class AdminWabaApiCallLogOut(BaseModel):
    id: str
    action: str
    status: str
    detail: str
    to_wa_id: str | None
    entity_id: str | None
    entity_name: str | None
    organization_name: str | None
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


class PlatformRazorpaySettingsOut(BaseModel):
    key_id: str | None
    key_secret_configured: bool


class PlatformRazorpaySettingsUpdate(BaseModel):
    key_id: str | None = None
    key_secret: str | None = None  # blank = keep the existing one, same convention as SMTP's password / R2's secret_access_key


class PlatformWabaSettingsOut(BaseModel):
    app_id: str | None
    config_id: str | None
    configured: bool
    webhook_url: str | None
    webhook_verify_token: str | None


class PlatformWabaSettingsUpdate(BaseModel):
    app_id: str | None = None
    config_id: str | None = None
    app_secret: str | None = None  # blank = keep the existing one, same convention as SMTP's password / R2's secret_access_key


class WabaTestConnectionResponse(BaseModel):
    ok: bool
    detail: str


class WabaWebhookTokenOut(BaseModel):
    webhook_url: str | None
    webhook_verify_token: str


class WabaConfigOut(BaseModel):
    app_id: str
    config_id: str


class WabaConnectRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    waba_id: str = Field(min_length=1, max_length=64)
    phone_number_id: str = Field(min_length=1, max_length=64)
    business_id: str | None = None


class RegisterPhoneRequest(BaseModel):
    """pin is optional -- omit it to reuse whatever PIN is already stored (or a freshly generated
    one on first-ever registration). Pass it explicitly when the number already had two-step
    verification enabled on Meta's side before it was connected here, so the auto-generated PIN
    Textzi would otherwise try doesn't mismatch Meta's real one (surfaces as a 400 "Invalid
    parameter" from Meta's own /register endpoint)."""
    pin: str | None = Field(default=None, pattern=r"^\d{6}$")


class WabaDirectConnectRequest(BaseModel):
    """Fallback path when Embedded Signup isn't set up yet (no Configuration ID) -- the caller
    already has a real access token from Meta directly (WhatsApp > API Setup's temporary token,
    or a permanent System User token from Business Settings), so there's no authorization code
    to exchange, just the token itself plus the IDs Meta's API Setup page already shows."""
    waba_id: str = Field(min_length=1, max_length=64)
    phone_number_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=1, max_length=4000)
    business_id: str | None = None


class WabaStatusOut(BaseModel):
    connected: bool
    phone_number: str | None = None
    verified_name: str | None = None
    waba_id: str | None = None
    connected_at: str | None = None
    quality_rating: str | None = None
    messaging_tier: str | None = None
    status_checked_at: str | None = None


class LabelOut(BaseModel):
    id: str
    scope: str
    name: str
    color: str


class LabelCreateRequest(BaseModel):
    scope: str = Field(pattern="^(conversation|contact)$")
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="primary", max_length=20)


class ContactOut(BaseModel):
    id: str
    wa_id: str | None
    email: str | None
    name: str | None
    custom_attributes: dict
    opted_out: bool
    labels: list[LabelOut] = []
    company_id: str | None = None
    consent_given_at: str | None = None
    consent_source: str | None = None
    crm_contact_id: str | None = None
    created_at: str


class ContactUpdateRequest(BaseModel):
    name: str | None = None
    custom_attributes: dict | None = None
    opted_out: bool | None = None


class CrmContactOut(BaseModel):
    id: str
    name: str | None
    phone: str | None
    email: str | None
    title: str | None
    company_id: str | None
    owner_user_id: str | None
    address: str | None
    reports_to_id: str | None
    source: str
    custom_fields: dict
    consent_given_at: str | None
    consent_source: str | None
    created_at: str


class CrmContactCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=120)
    company_id: str | None = None
    owner_user_id: str | None = None
    address: str | None = None
    reports_to_id: str | None = None
    source: str = Field(default="manual", pattern="^(whatsapp_conversation|manual|web_form|csv_import)$")
    custom_fields: dict | None = None


class CrmContactUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = None
    email: EmailStr | None = None
    title: str | None = None
    company_id: str | None = None
    owner_user_id: str | None = None
    address: str | None = None
    reports_to_id: str | None = None
    custom_fields: dict | None = None


class CustomFieldDefinitionOut(BaseModel):
    id: str
    applies_to: str
    name: str
    field_type: str
    options: list[str]
    required: bool
    position: int


class CustomFieldDefinitionCreateRequest(BaseModel):
    applies_to: str = Field(pattern="^(lead|deal|crm_contact|customer|ticket)$")
    name: str = Field(min_length=1, max_length=60)
    field_type: str = Field(default="text", pattern="^(text|number|date|dropdown)$")
    options: list[str] = Field(default_factory=list)
    required: bool = False


class ConversationMessageOut(BaseModel):
    id: str
    direction: str
    is_private: bool
    message_type: str
    body: str | None
    media_url: str | None
    payload: dict | None = None
    status: str | None
    error: str | None = None
    sent_by_user_id: str | None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    contact: ContactOut
    channel: str
    status: str
    assigned_user_id: str | None
    last_message_at: str | None
    last_read_at: str | None
    last_message_preview: str | None = None
    unread: bool = False
    is_ticket: bool = False
    ticket_number: str | None = None
    created_at: str
    labels: list[LabelOut] = []
    first_response_due_at: str | None = None
    sla_breached: bool = False
    resolution_due_at: str | None = None
    resolution_breached: bool = False
    priority: str = "medium"
    category: str = "question"
    group_id: str | None = None
    ticket_custom_fields: dict = {}
    subject: str | None = None
    cc_emails: list[str] = []


class ConversationSubjectUpdateRequest(BaseModel):
    subject: str | None = Field(default=None, max_length=300)


class ConversationCcUpdateRequest(BaseModel):
    cc_emails: list[EmailStr] = Field(default_factory=list, max_length=10)


class TicketGroupOut(BaseModel):
    id: str
    name: str
    member_user_ids: list[str]


class TicketGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    member_user_ids: list[str] = Field(default_factory=list)


class TicketPriorityUpdateRequest(BaseModel):
    priority: str = Field(pattern="^(low|medium|high|urgent)$")


class TicketCategoryUpdateRequest(BaseModel):
    category: str = Field(pattern="^(question|incident|problem|task)$")


class TicketGroupAssignRequest(BaseModel):
    group_id: str | None = None


class TicketCustomFieldsUpdateRequest(BaseModel):
    ticket_custom_fields: dict


class ConversationCountsOut(BaseModel):
    unassigned: int
    assigned_to_me: int
    all: int


class TicketCountsOut(BaseModel):
    """Every status's count at once, regardless of which one the ticket list currently has
    selected -- unlike ConversationCountsOut (which deliberately mirrors whatever status filter
    is active, for the plain WhatsApp inbox), a ticket list needs every count visible up front so
    a status with zero tickets in view never reads as "nothing exists at all"."""
    unassigned: int
    assigned_to_me: int
    all: int
    open: int
    pending: int
    resolved: int


class ConversationDetailOut(ConversationOut):
    messages: list[ConversationMessageOut]


class ConversationUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|pending|resolved)$")
    assigned_user_id: str | None = None


class AssignableUserOut(BaseModel):
    id: str
    full_name: str
    email: str


class TemplateButtonOut(BaseModel):
    type: str
    text: str
    url: str | None = None
    phone_number: str | None = None


class WabaTemplateOut(BaseModel):
    name: str
    status: str
    language: str
    category: str
    header_text: str | None = None
    body: str | None
    footer_text: str | None = None
    buttons: list[TemplateButtonOut] = []


class TemplateMessageRequest(BaseModel):
    template_name: str = Field(min_length=1, max_length=512)
    language_code: str = Field(min_length=1, max_length=20)
    body_params: list[str] = []
    preview_body: str = Field(min_length=1, max_length=4096)


class StartConversationRequest(BaseModel):
    """Kicks off a first-touch conversation to a number that's never messaged in -- WhatsApp only
    allows this via an approved template (never free-form text), same restriction as re-engaging
    a conversation whose 24-hour window has closed."""
    wa_id: str = Field(min_length=1, max_length=30)
    name: str | None = Field(default=None, max_length=160)
    template_name: str = Field(min_length=1, max_length=512)
    language_code: str = Field(min_length=1, max_length=20)
    body_params: list[str] = []
    preview_body: str = Field(min_length=1, max_length=4096)


class TemplateButtonRequest(BaseModel):
    type: str = Field(pattern="^(QUICK_REPLY|URL|PHONE_NUMBER)$")
    text: str = Field(min_length=1, max_length=25)
    url: str | None = Field(default=None, max_length=2000)
    phone_number: str | None = Field(default=None, max_length=20)


class TemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=512, pattern="^[a-z0-9_]+$")
    category: str = Field(pattern="^(MARKETING|UTILITY|AUTHENTICATION)$")
    language: str = Field(min_length=1, max_length=20)
    header_text: str | None = Field(default=None, max_length=60)
    body_text: str = Field(min_length=1, max_length=1024)
    example_params: list[str] = []
    footer_text: str | None = Field(default=None, max_length=60)
    buttons: list[TemplateButtonRequest] = []


class LocationMessageRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)


class ContactCardEntry(BaseModel):
    """Mirrors Meta's own contacts-message shape closely enough to pass straight through --
    only the fields this composer actually collects, not the full breadth Meta's schema allows
    (addresses, org, birthday, urls) since nothing in the UI collects those yet."""
    formatted_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=30)


class ContactMessageRequest(BaseModel):
    contacts: list[ContactCardEntry] = Field(min_length=1, max_length=10)


class InteractiveButtonRequest(BaseModel):
    body_text: str = Field(min_length=1, max_length=1024)
    button_labels: list[str] = Field(min_length=1, max_length=3)


class InteractiveListRow(BaseModel):
    title: str = Field(min_length=1, max_length=24)
    description: str | None = Field(default=None, max_length=72)


class InteractiveListRequest(BaseModel):
    body_text: str = Field(min_length=1, max_length=1024)
    button_label: str = Field(min_length=1, max_length=20)
    rows: list[InteractiveListRow] = Field(min_length=1, max_length=10)


class ReactionRequest(BaseModel):
    message_id: str = Field(min_length=1)
    emoji: str = Field(max_length=8)


class BusinessProfileOut(BaseModel):
    about: str | None = None
    address: str | None = None
    description: str | None = None
    email: str | None = None
    profile_picture_url: str | None = None
    websites: list[str] = []
    vertical: str | None = None


class BusinessProfileUpdateRequest(BaseModel):
    about: str | None = Field(default=None, max_length=139)
    address: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=512)
    email: str | None = Field(default=None, max_length=128)
    vertical: str | None = None
    websites: list[str] | None = None


class WabaStatusRefreshOut(BaseModel):
    quality_rating: str | None
    messaging_tier: str | None
    status_checked_at: str | None


class AutomationRuleOut(BaseModel):
    id: str
    name: str
    trigger_type: str
    trigger_value: str | None
    action_type: str
    action_value: str
    active: bool
    priority: int


class AutomationRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    trigger_type: str = Field(pattern="^(keyword|new_contact)$")
    trigger_value: str | None = Field(default=None, max_length=200)
    action_type: str = Field(pattern="^(assign|reply|label)$")
    action_value: str = Field(min_length=1, max_length=64)
    active: bool = True
    priority: int = 0


class ConversationMessageCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4096)
    is_private: bool = False


class CannedResponseOut(BaseModel):
    id: str
    shortcut: str
    body: str


class CannedResponseCreateRequest(BaseModel):
    shortcut: str = Field(min_length=1, max_length=25)
    body: str = Field(min_length=1, max_length=500)


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
    channel_scope: str | None = Field(default=None, pattern="^(sms|waba|crm)$")
    # Only meaningful alongside a single channel_scope -- null means every page in that channel
    # (today's behavior). Frontend-enforced only; see permissions.require_channel_scope for the
    # actual security boundary.
    page_scope: list[str] | None = None


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
    manager_id: str | None = None
    channel_scope: str | None = None
    page_scope: list[str] | None = None


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


# --- CRM (3rd channel) -----------------------------------------------------------------------

class LeadOut(BaseModel):
    id: str
    contact: CrmContactOut
    company_name: str | None
    source: str
    status: str
    owner_user_id: str | None
    notes: str | None
    custom_fields: dict
    score: int
    converted_at: str | None
    converted_deal_id: str | None
    created_at: str


class LeadCreateRequest(BaseModel):
    # Either contact_id (attach to an existing CrmContact) or name (find-or-create a new one by
    # phone/email) must be given -- enforced in the endpoint itself since Pydantic can't easily
    # express "one of these two" as a field default.
    contact_id: str | None = None
    name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=120)
    company_name: str | None = Field(default=None, max_length=160)
    source: str = Field(default="manual", pattern="^(whatsapp_conversation|manual|web_form|csv_import)$")
    owner_user_id: str | None = None
    notes: str | None = None
    custom_fields: dict | None = None


class LeadUpdateRequest(BaseModel):
    company_name: str | None = None
    status: str | None = Field(default=None, pattern="^(new|contacted|qualified|unqualified)$")
    owner_user_id: str | None = None
    notes: str | None = None
    custom_fields: dict | None = None


class LeadConvertRequest(BaseModel):
    deal_name: str | None = Field(default=None, max_length=160)
    pipeline_id: str | None = None
    stage: str = Field(default="inquiry", min_length=1, max_length=40)
    value: float | None = Field(default=None, ge=0)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: str | None = None


class DealOut(BaseModel):
    id: str
    name: str | None
    contact: CrmContactOut
    pipeline_id: str | None
    stage: str
    source: str
    converted_from_conversation_id: str | None
    converted_from_lead_id: str | None
    owner_user_id: str | None
    notes: str | None
    value: float | None
    probability: int | None
    expected_close_date: str | None
    status: str
    lost_reason: str | None
    next_step: str | None
    next_step_due_at: str | None
    custom_fields: dict
    stage_approvals: dict
    created_at: str


class DealUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    value: float | None = Field(default=None, ge=0)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: str | None = None
    next_step: str | None = Field(default=None, max_length=300)
    next_step_due_at: str | None = None
    custom_fields: dict | None = None


class DealStageEventOut(BaseModel):
    stage: str
    entered_at: str
    exited_at: str | None
    minutes: int | None
    changed_by_user_id: str | None
    changed_by_name: str | None


class DealStageHistoryOut(BaseModel):
    events: list[DealStageEventOut]


class DealStatusUpdateRequest(BaseModel):
    status: str = Field(pattern="^(open|won|lost)$")
    lost_reason: str | None = Field(default=None, max_length=200)


class PipelineStageIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    probability: int = Field(ge=0, le=100)
    forecast_category: str = Field(default="pipeline", pattern="^(pipeline|commit|omitted)$")
    # Field names (built-in: value/probability/expected_close_date/owner_user_id, or a custom
    # field name) that must be filled on the deal before it can move OUT of this stage. Empty
    # list -- the default -- means no requirement, matching every pipeline that predates this.
    required_fields: list[str] = Field(default_factory=list)
    # User.id list -- every one of them must have approved (Deal.stage_approvals[this stage]) via
    # POST /deals/{id}/stage-approvals/{stage}/approve before the deal can leave this stage. Empty
    # list -- the default -- means no approval requirement.
    required_approval_user_ids: list[str] = Field(default_factory=list)


class PipelineStageOut(PipelineStageIn):
    pass


class PipelineOut(BaseModel):
    id: str
    name: str
    stages: list[PipelineStageOut]


class PipelineCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    stages: list[PipelineStageIn] = Field(min_length=1, max_length=15)


class CrmFunnelStage(BaseModel):
    stage: str
    count: int
    value: float


class LeadFunnelMonth(BaseModel):
    month: str
    count: int


class LeadFunnelOut(BaseModel):
    created_count: int
    converted_count: int
    conversion_rate: float | None
    monthly_created: list[LeadFunnelMonth]


class CrmReportsOut(BaseModel):
    funnel: list[CrmFunnelStage]
    forecast: float
    open_value: float
    won_value: float
    lost_value: float
    open_count: int
    won_count: int
    lost_count: int
    win_rate: float | None
    lead_funnel: LeadFunnelOut


class EmployeeSalesRow(BaseModel):
    user_id: str
    full_name: str
    won_count: int
    won_value: float


class ProductSalesRow(BaseModel):
    description: str
    count: int
    value: float


class FollowUpPerformanceOut(BaseModel):
    total: int
    done: int
    overdue: int
    done_rate: float | None


class CrmExtendedReportsOut(BaseModel):
    by_employee: list[EmployeeSalesRow]
    by_product: list[ProductSalesRow]
    outstanding_count: int
    outstanding_value: float
    follow_up: FollowUpPerformanceOut


class ReportRunRequest(BaseModel):
    object_type: str = Field(pattern="^(deal|lead|task)$")
    group_by: str = Field(min_length=1, max_length=40)
    measure: str = Field(min_length=1, max_length=40)
    filters: dict[str, str] = Field(default_factory=dict)


class ReportRow(BaseModel):
    label: str
    value: float


class ReportRunResult(BaseModel):
    rows: list[ReportRow]


class ReportDrillDownRequest(BaseModel):
    object_type: str = Field(pattern="^(deal|lead|task)$")
    group_by: str = Field(min_length=1, max_length=40)
    group_value: str = Field(min_length=1, max_length=200)
    filters: dict[str, str] = Field(default_factory=dict)


class ReportDrillDownRow(BaseModel):
    id: str
    label: str
    sublabel: str | None


class ReportDrillDownResult(BaseModel):
    rows: list[ReportDrillDownRow]


class SavedReportOut(BaseModel):
    id: str
    name: str
    object_type: str
    group_by: str
    measure: str
    chart_type: str
    filters: dict[str, str]
    schedule: str | None
    created_at: str


class SavedReportCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    object_type: str = Field(pattern="^(deal|lead|task)$")
    group_by: str = Field(min_length=1, max_length=40)
    measure: str = Field(min_length=1, max_length=40)
    chart_type: str = Field(default="bar", pattern="^(bar|donut|table)$")
    filters: dict[str, str] = Field(default_factory=dict)
    schedule: str | None = Field(default=None, pattern="^(weekly|monthly)$")


class SavedReportUpdateRequest(BaseModel):
    schedule: str | None = Field(default=None, pattern="^(weekly|monthly)$")


class TaskOut(BaseModel):
    id: str
    contact_id: str
    deal_id: str | None
    title: str
    type: str
    due_at: str | None
    duration_minutes: int | None
    done: bool
    assigned_user_id: str | None
    recurrence: str
    priority: str
    outcome: str | None
    created_at: str


class TaskCreateRequest(BaseModel):
    contact_id: str
    deal_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    type: str = Field(default="follow_up", pattern="^(call|meeting|follow_up|other)$")
    due_at: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    assigned_user_id: str | None = None
    recurrence: str = Field(default="none", pattern="^(none|daily|weekly|monthly)$")
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")


class TaskUpdateRequest(BaseModel):
    deal_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = Field(default=None, pattern="^(call|meeting|follow_up|other)$")
    due_at: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    done: bool | None = None
    assigned_user_id: str | None = None
    recurrence: str | None = Field(default=None, pattern="^(none|daily|weekly|monthly)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high)$")
    outcome: str | None = None


class QuoteLineItem(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    hsn_code: str = Field(default="", max_length=20)
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)
    # Optional -- which Product this line was populated from, if any (kept for reference only;
    # description/hsn_code/unit_price above are this line's own snapshot and never re-read from
    # the product later, same reasoning as Product's own model docstring).
    product_id: str | None = None


class ProductOut(BaseModel):
    id: str
    name: str
    sku: str | None
    hsn_code: str
    unit_price: float
    description: str | None
    active: bool


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=60)
    hsn_code: str = Field(default="", max_length=20)
    unit_price: float = Field(ge=0)
    description: str | None = None
    active: bool = True


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, max_length=60)
    hsn_code: str | None = Field(default=None, max_length=20)
    unit_price: float | None = Field(default=None, ge=0)
    description: str | None = None
    active: bool | None = None


class DocumentTemplateOut(BaseModel):
    id: str
    name: str
    applies_to: str
    body: str
    created_at: str


class DocumentTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    applies_to: str = Field(default="proposal", pattern="^(proposal|contract|other)$")
    body: str = Field(min_length=1)


class DocumentTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    applies_to: str | None = Field(default=None, pattern="^(proposal|contract|other)$")
    body: str | None = Field(default=None, min_length=1)


class QuoteOut(BaseModel):
    id: str
    deal_id: str
    quote_number: str | None
    line_items: list[QuoteLineItem]
    status: str
    subtotal: float
    cgst: float
    sgst: float
    igst: float
    total: float
    has_pdf: bool
    approval_status: str
    approvals: list[dict]
    approvers_required: list[str]
    converted_invoice_id: str | None
    created_at: str
    sent_at: str | None


class QuoteCreateRequest(BaseModel):
    deal_id: str
    line_items: list[QuoteLineItem] = Field(min_length=1)


class QuoteLineItemsUpdateRequest(BaseModel):
    line_items: list[QuoteLineItem] = Field(min_length=1)


class CompanyOut(BaseModel):
    id: str
    name: str
    gstin: str | None
    industry: str | None
    website: str | None
    notes: str | None
    owner_user_id: str | None
    account_type: str | None
    parent_company_id: str | None
    phone: str | None
    address: str | None
    employee_count: int | None
    annual_revenue: float | None
    contact_count: int
    open_deal_value: float
    won_deal_value: float
    open_deal_count: int
    created_at: str


class CompanyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    gstin: str | None = Field(default=None, max_length=15)
    industry: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    owner_user_id: str | None = None
    account_type: str | None = Field(default=None, pattern="^(customer|partner|prospect|vendor)$")
    parent_company_id: str | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    annual_revenue: float | None = Field(default=None, ge=0)


class ScoringRuleOut(BaseModel):
    id: str
    name: str
    condition_type: str
    condition_value: str
    points: int
    active: bool


class ScoringRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    condition_type: str = Field(pattern="^(has_label|custom_field_set|source)$")
    condition_value: str = Field(min_length=1, max_length=200)
    points: int = Field(default=10, ge=-100, le=100)
    active: bool = True


class ScoringRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    condition_type: str | None = Field(default=None, pattern="^(has_label|custom_field_set|source)$")
    condition_value: str | None = Field(default=None, min_length=1, max_length=200)
    points: int | None = Field(default=None, ge=-100, le=100)
    active: bool | None = None


class TerritoryOut(BaseModel):
    id: str
    name: str
    pincodes: list[str]
    owner_user_id: str | None
    parent_territory_id: str | None


class TerritoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    pincodes: list[str] = Field(min_length=1)
    owner_user_id: str | None = None
    parent_territory_id: str | None = None


class TerritoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    pincodes: list[str] | None = Field(default=None, min_length=1)
    owner_user_id: str | None = None
    parent_territory_id: str | None = None


class SalesTargetOut(BaseModel):
    id: str
    user_id: str
    period_start: str
    period_end: str
    target_value: float
    actual_value: float


class SalesTargetCreateRequest(BaseModel):
    user_id: str
    period_start: str
    period_end: str
    target_value: float = Field(gt=0)


class SalesTargetUpdateRequest(BaseModel):
    period_start: str | None = None
    period_end: str | None = None
    target_value: float | None = Field(default=None, gt=0)


class AttachmentOut(BaseModel):
    id: str
    contact_id: str
    filename: str
    uploaded_by_user_id: str | None
    created_at: str


class WebFormOut(BaseModel):
    enabled: bool
    fields: list[str]
    success_message: str
    target_pipeline_id: str | None
    embed_snippet: str


class WebFormUpdateRequest(BaseModel):
    enabled: bool
    fields: list[str] = Field(min_length=1)
    success_message: str = Field(min_length=1, max_length=300)
    target_pipeline_id: str | None = None


class WebFormSubmitRequest(BaseModel):
    values: dict[str, str]
    turnstile_token: str | None = None


class EmailAccountOut(BaseModel):
    connected: bool
    from_name: str | None = None
    from_email: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_use_tls: bool = True
    imap_host: str | None = None
    imap_port: int | None = None
    imap_username: str | None = None
    imap_use_ssl: bool = True
    status: str | None = None
    last_error: str | None = None
    last_synced_at: str | None = None


class EmailAccountUpdateRequest(BaseModel):
    from_name: str | None = Field(default=None, max_length=160)
    from_email: EmailStr
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(min_length=1, max_length=255)
    smtp_password: str = Field(min_length=1)
    smtp_use_tls: bool = True
    imap_host: str = Field(min_length=1, max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_username: str = Field(min_length=1, max_length=255)
    imap_password: str = Field(min_length=1)
    imap_use_ssl: bool = True


class EmailAccountTestResult(BaseModel):
    ok: bool
    error: str | None = None


class MailboxProvisionRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9.]+$")


class EmailSendRequest(BaseModel):
    # Either contact_id (reply within an existing thread) or to_email (compose to a new/known
    # address, found-or-created on the spot) must be given.
    contact_id: str | None = None
    to_email: EmailStr | None = None
    to_name: str | None = Field(default=None, max_length=160)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    cc: list[EmailStr] = Field(default_factory=list, max_length=10)
    quote_id: str | None = None


class WebFormSubmitResponse(BaseModel):
    message: str


class PublicWebFormOut(BaseModel):
    enabled: bool
    fields: list[str]


class ManagerUpdateRequest(BaseModel):
    manager_id: str | None = None


class LeadRoutingRuleOut(BaseModel):
    id: str
    name: str
    trigger_type: str
    trigger_value: str
    assign_to_user_id: str
    active: bool
    priority: int


class LeadRoutingRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    trigger_type: str = Field(pattern="^(pincode|source|product|territory)$")
    trigger_value: str = Field(min_length=1, max_length=200)
    assign_to_user_id: str
    active: bool = True
    priority: int = 0


class LeadRoutingRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    trigger_type: str | None = Field(default=None, pattern="^(pincode|source|product|territory)$")
    trigger_value: str | None = Field(default=None, min_length=1, max_length=200)
    assign_to_user_id: str | None = None
    active: bool | None = None
    priority: int | None = None


class SequenceStepIn(BaseModel):
    day_offset: int = Field(ge=0, le=365)
    # "sms" deliberately excluded -- Indian SMS legally requires a pre-registered DLT template,
    # so a free-text sequence step could never actually send; better to reject it here than accept
    # it and silently no-op at send time.
    channel: str = Field(pattern="^(whatsapp_template|task)$")
    content: dict
    # The one per-step branching primitive -- see SequenceStep's own model docstring.
    only_if_stage: str | None = None


class SequenceStepOut(SequenceStepIn):
    id: str


class SequenceOut(BaseModel):
    id: str
    name: str
    active: bool
    exit_stage: str | None
    steps: list[SequenceStepOut]
    enrolled_count: int
    created_at: str


class SequenceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    exit_stage: str | None = None
    steps: list[SequenceStepIn] = Field(min_length=1)


class SequenceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    exit_stage: str | None = Field(default=None)
    active: bool | None = None
    steps: list[SequenceStepIn] | None = Field(default=None, min_length=1)


class SequenceEnrollRequest(BaseModel):
    deal_id: str


class ConsentUpdateRequest(BaseModel):
    consent_source: str = Field(min_length=1, max_length=60)


class LeadCreateFromConversationRequest(BaseModel):
    company_name: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=120)
    owner_user_id: str | None = None
    notes: str | None = None


class DealCreateFromConversationRequest(BaseModel):
    deal_name: str | None = Field(default=None, max_length=160)
    pipeline_id: str | None = None
    stage: str = Field(default="inquiry", min_length=1, max_length=40)
    value: float | None = Field(default=None, ge=0)
    probability: int | None = Field(default=None, ge=0, le=100)
    owner_user_id: str | None = None
    notes: str | None = None


class DealCreateRequest(BaseModel):
    # Same "contact_id or name" contract as LeadCreateRequest -- lets an agent open the Deals
    # page and add a brand-new deal without first having to find or create a contact elsewhere.
    # name is the CONTACT's name (find-or-create); deal_name is the deal's own, distinct name
    # (Zoho/SF's Opportunity Name) -- kept as two fields since a deal can be named differently
    # from its contact (e.g. "Acme Corp -- Annual Renewal").
    contact_id: str | None = None
    name: str | None = Field(default=None, max_length=160)
    deal_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=120)
    pipeline_id: str | None = None
    stage: str = Field(default="inquiry", min_length=1, max_length=40)
    value: float | None = Field(default=None, ge=0)
    probability: int | None = Field(default=None, ge=0, le=100)
    owner_user_id: str | None = None
    notes: str | None = None
    custom_fields: dict | None = None


class CustomerCreateFromConversationRequest(BaseModel):
    owner_user_id: str | None = None
    notes: str | None = None


class CustomerCreateRequest(BaseModel):
    contact_id: str | None = None
    name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=120)
    owner_user_id: str | None = None
    notes: str | None = None
    custom_fields: dict | None = None


class DealStageUpdateRequest(BaseModel):
    stage: str = Field(min_length=1, max_length=40)


class DealOwnerUpdateRequest(BaseModel):
    owner_user_id: str | None = None


class DealNotesUpdateRequest(BaseModel):
    notes: str | None = None


class CustomerOut(BaseModel):
    id: str
    contact: CrmContactOut
    deal_id: str | None
    converted_from_conversation_id: str | None
    owner_user_id: str | None
    notes: str | None
    custom_fields: dict
    created_at: str


class CustomerUpdateRequest(BaseModel):
    owner_user_id: str | None = None
    notes: str | None = None
    custom_fields: dict | None = None


class CustomerDetailOut(CustomerOut):
    tasks: list[TaskOut]


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str
    link: str | None
    read: bool
    created_at: str


class MapToCustomerRequest(BaseModel):
    customer_id: str


class TicketSummary(BaseModel):
    open: int
    resolved: int


class ContactDirectoryEntryOut(BaseModel):
    contact: ContactOut
    conversation_id: str | None
    last_message_at: str | None
    last_reply_at: str | None
    is_ticket: bool
    ticket_number: str | None
    ticket_status: str | None
    lead_id: str | None
    customer_id: str | None


class CrmSettingsOut(BaseModel):
    pipeline_stages: list[str]
    notify_email: bool
    notify_sms: bool
    notify_whatsapp: bool
    logo_url: str | None
    brand_color: str | None
    quote_approval_threshold: float | None
    quote_approver_user_ids: list[str]


class CrmSettingsUpdateRequest(BaseModel):
    notify_email: bool
    notify_sms: bool
    notify_whatsapp: bool
    brand_color: str | None = Field(default=None, max_length=20)
    quote_approval_threshold: float | None = Field(default=None, ge=0)
    quote_approver_user_ids: list[str] | None = None


class PipelineStagesUpdateRequest(BaseModel):
    stages: list[str] = Field(min_length=1, max_length=15)


class ContactTimelineOut(BaseModel):
    contact: ContactOut
    conversation_id: str | None
    # Set once this WhatsApp contact has been converted into CRM (Contact.crm_contact_id) --
    # null if it never has been. Attachments and other CRM-contact-scoped actions need this,
    # since they're addressed by CrmContact id, not this WhatsApp contact's own id.
    crm_contact_id: str | None
    lead: LeadOut | None
    deals: list[DealOut]
    customer: CustomerOut | None
    tickets: TicketSummary
    messages: list[ConversationMessageOut]


# --- Record detail pages (Addendum 12, Phase 1) -------------------------------------------------

class ActivityMessageOut(BaseModel):
    id: str
    channel: str
    direction: str
    message_type: str
    body: str | None
    created_at: str


class LeadDetailOut(BaseModel):
    lead: LeadOut
    company: CompanyOut | None
    tasks: list[TaskOut]
    waba_contact_id: str | None
    recent_messages: list[ActivityMessageOut]


class DealDetailOut(BaseModel):
    deal: DealOut
    company: CompanyOut | None
    tasks: list[TaskOut]
    quotes: list[QuoteOut]
    waba_contact_id: str | None
    recent_messages: list[ActivityMessageOut]


class CrmContactDetailOut(BaseModel):
    contact: CrmContactOut
    company: CompanyOut | None
    leads: list[LeadOut]
    deals: list[DealOut]
    customers: list[CustomerOut]
    tasks: list[TaskOut]
    attachments: list[AttachmentOut]
    waba_contact_id: str | None
    reports_to: CrmContactOut | None = None
    direct_reports: list[CrmContactOut] = []


class CompanySummary(BaseModel):
    id: str
    name: str


class CompanyDetailOut(BaseModel):
    company: CompanyOut
    contacts: list[CrmContactOut]
    parent_company: CompanySummary | None = None
    child_companies: list[CompanySummary] = []


# --- Global search (Addendum 12, Phase 2) ---------------------------------------------------

class SearchResultRow(BaseModel):
    id: str
    label: str
    sublabel: str | None


class SearchResultsOut(BaseModel):
    leads: list[SearchResultRow]
    deals: list[SearchResultRow]
    contacts: list[SearchResultRow]
    companies: list[SearchResultRow]


# --- Bulk actions & saved views (Addendum 12, Phase 3) --------------------------------------

class LeadBulkOwnerRequest(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=200)
    owner_user_id: str | None = None


class DealBulkOwnerRequest(BaseModel):
    deal_ids: list[str] = Field(min_length=1, max_length=200)
    owner_user_id: str | None = None


class LeadBulkDeleteRequest(BaseModel):
    lead_ids: list[str] = Field(min_length=1, max_length=200)


class DealBulkDeleteRequest(BaseModel):
    deal_ids: list[str] = Field(min_length=1, max_length=200)


class DealBulkStageRequest(BaseModel):
    deal_ids: list[str] = Field(min_length=1, max_length=200)
    stage: str


class DealBulkStageResult(BaseModel):
    updated: list[DealOut]
    skipped: dict[str, str]  # deal_id -> why it couldn't move (missing required fields / approval)


class CompanyBulkDeleteRequest(BaseModel):
    company_ids: list[str] = Field(min_length=1, max_length=200)


class CustomerBulkDeleteRequest(BaseModel):
    customer_ids: list[str] = Field(min_length=1, max_length=200)


class SavedViewOut(BaseModel):
    id: str
    applies_to: str
    name: str
    filters: dict
    created_at: str


class SavedViewCreateRequest(BaseModel):
    applies_to: str = Field(pattern="^(lead|deal|crm_contact)$")
    name: str = Field(min_length=1, max_length=80)
    filters: dict = {}


# --- CSV import (Addendum 13) ----------------------------------------------------------------

class ImportResultOut(BaseModel):
    created: int
    skipped: int
    errors: list[str]


# --- Duplicate detection & merge (Addendum 13) ------------------------------------------------

class DuplicateGroupOut(BaseModel):
    match_on: str  # "phone" | "email"
    contacts: list[CrmContactOut]


class MergeContactsRequest(BaseModel):
    primary_id: str
    duplicate_ids: list[str] = Field(min_length=1, max_length=10)


# --- Segments & campaigns ----------------------------------------------------------------------

class SegmentOut(BaseModel):
    id: str
    name: str
    label_ids: list[str]
    custom_attributes: dict
    contact_count: int
    created_at: str


class SegmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    label_ids: list[str] = []
    custom_attributes: dict = {}


class CampaignOut(BaseModel):
    id: str
    name: str
    template_name: str
    template_language: str
    body_params: list[str]
    segment_id: str
    status: str
    total_recipients: int
    sent_count: int
    failed_count: int
    created_at: str
    completed_at: str | None


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template_name: str = Field(min_length=1, max_length=512)
    template_language: str = Field(min_length=1, max_length=20)
    body_params: list[str] = []
    segment_id: str


# --- Business hours & SLA ----------------------------------------------------------------------

class DayHours(BaseModel):
    open: str
    close: str


class BusinessHoursOut(BaseModel):
    enabled: bool
    timezone: str
    schedule: dict[str, DayHours]
    outside_hours_message: str | None


class BusinessHoursUpdateRequest(BaseModel):
    enabled: bool
    timezone: str = Field(default="Asia/Kolkata", max_length=50)
    schedule: dict[str, DayHours] = {}
    outside_hours_message: str | None = Field(default=None, max_length=500)


class SlaPolicyOut(BaseModel):
    enabled: bool
    first_response_minutes: int
    resolution_minutes: int


class SlaPolicyUpdateRequest(BaseModel):
    enabled: bool
    first_response_minutes: int = Field(gt=0, le=10080)
    resolution_minutes: int = Field(gt=0, le=43200)


class AgentCapacityUpdateRequest(BaseModel):
    max_open_conversations: int | None = Field(default=None, gt=0)


# --- Macros --------------------------------------------------------------------------------------

class MacroAction(BaseModel):
    type: str = Field(pattern="^(reply|label|status|assign)$")
    value: str | None = None


class MacroOut(BaseModel):
    id: str
    name: str
    actions: list[MacroAction]
    created_at: str


class MacroCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    actions: list[MacroAction] = Field(min_length=1)


# --- CSAT ----------------------------------------------------------------------------------------

class CsatSettingsOut(BaseModel):
    enabled: bool


class CsatSettingsUpdateRequest(BaseModel):
    enabled: bool


class CsatResponseOut(BaseModel):
    id: str
    conversation_id: str
    rating: int | None
    requested_at: str
    responded_at: str | None


# --- Outbound webhooks -----------------------------------------------------------------------

class WabaWebhookSubscriptionOut(BaseModel):
    url: str | None
    enabled: bool
    secret: str | None = None


class WabaWebhookSubscriptionUpdateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    enabled: bool = True


# --- Reporting -------------------------------------------------------------------------------

class ReportVolumePoint(BaseModel):
    date: str
    inbound: int
    outbound: int


class ReportAgentRow(BaseModel):
    user_id: str
    full_name: str
    messages_sent: int
    conversations_resolved: int
    avg_first_response_minutes: float | None


class ReportLabelRow(BaseModel):
    label_id: str
    name: str
    color: str
    conversation_count: int


class WabaReportsOut(BaseModel):
    volume: list[ReportVolumePoint]
    agents: list[ReportAgentRow]
    labels: list[ReportLabelRow]
    total_conversations: int
    open_conversations: int
    resolved_conversations: int
    sla_breached_count: int
    avg_csat: float | None
    csat_response_count: int
