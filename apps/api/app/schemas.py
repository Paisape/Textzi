from typing import Any, Literal
from pydantic import BaseModel, EmailStr, Field, field_validator
from .models import MessageCategory, Status, UserRole, UserStatus
from .security import assert_safe_webhook_url


class SmsSendRequest(BaseModel):
    """Dashboard Compose only (sms.py's compose_sms) -- a human filling out a form benefits from
    picking a template by its readable alias and letting Textzi fill in the variables live, with
    a preview. The external developer API (main.py) uses ApiSmsSendRequest instead: the caller's
    own system already has the complete message text, so there's nothing for Textzi to render."""
    template: str = Field(pattern=r"^[a-z0-9_\-]{2,80}$")
    mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")
    variables: dict[str, str] = Field(default_factory=dict)


class SmsSendResponse(BaseModel):
    status: str
    message_id: str
    route: str
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
    subject_type: str = Field(pattern="^(group|user)$")
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
    alias: str = Field(pattern=r"^[a-z0-9_\-]{2,80}$")
    dlt_template_id: str = Field(min_length=3, max_length=80)
    body: str = Field(min_length=1, max_length=1600)
    category: MessageCategory = MessageCategory.transactional


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    next_step: str
    dev_email_code: str | None = None


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


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


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
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class Verify2faRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


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


class OrganizationOnboardRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    entity_name: str | None = Field(default=None, max_length=160)
    # gstin stays optional -- the onboarding form lets a user declare "I don't have a GSTIN" and
    # skip it entirely; every other KYC/contact field below is mandatory for self-service
    # onboarding (unlike AdminCreateCustomerRequest, which keeps all of these optional since an
    # admin may be provisioning a customer before full KYC details are available).
    gstin: str | None = Field(default=None, min_length=15, max_length=15)
    pan: str = Field(min_length=10, max_length=10)
    industry: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=300)
    contact_person_name: str = Field(min_length=2, max_length=160)
    contact_email: EmailStr
    contact_mobile: str = Field(pattern=r"^[1-9][0-9]{9,14}$")


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


class MessageOut(BaseModel):
    id: str
    recipient: str
    rendered_body: str
    status: str
    route: str | None
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


class DltDocumentOut(BaseModel):
    id: str
    filename: str


class DltOnboardingRequestOut(BaseModel):
    id: str
    status: str
    notes: str | None
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
    created_at: str


class DeliveryAttemptTelemetryOut(BaseModel):
    id: str
    route: str
    status: str
    provider_message_id: str | None
    error: str | None
    delivery_status_code: int | None
    delivered_at: str | None
    request_payload: dict[str, Any] | None
    response_body: str | None
    webhook_payload: dict[str, Any] | None
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


class WalletCreditRequest(BaseModel):
    entity_id: str
    amount: float = Field(gt=0, le=1_000_000)
    generate_invoice: bool = True
    notes: str | None = Field(default=None, max_length=300)


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


class PlatformErpNextSettingsOut(BaseModel):
    base_url: str | None
    api_key: str | None
    company: str | None
    cgst_account_head: str | None
    sgst_account_head: str | None
    print_format: str | None
    customer_group: str
    territory: str
    item_code_wallet_recharge: str | None
    item_code_dlt_fee: str | None
    item_code_channel_subscription: str | None
    item_code_admin_credit: str | None
    configured: bool


class PlatformErpNextSettingsUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    api_secret: str | None = None  # blank = keep the existing one, same convention as SMTP's password
    company: str | None = None
    cgst_account_head: str | None = None
    sgst_account_head: str | None = None
    print_format: str | None = None
    customer_group: str = "All Customer Groups"
    territory: str = "All Territories"
    item_code_wallet_recharge: str | None = None
    item_code_dlt_fee: str | None = None
    item_code_channel_subscription: str | None = None
    item_code_admin_credit: str | None = None


class ErpNextRetryResponse(BaseModel):
    invoice_id: str
    erpnext_sync_status: str
    erpnext_invoice_name: str | None
    erpnext_sync_error: str | None


class ErpNextCallLogOut(BaseModel):
    id: str
    invoice_id: str | None
    invoice_number: str | None
    method: str
    path: str
    status: str
    status_code: int | None
    error: str | None
    created_at: str


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
