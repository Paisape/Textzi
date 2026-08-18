import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .config import settings
from .email_service import render_email, send_email
from .models import ADMIN_ROLES, AccountActivity, ApiKey, BillingPlan, ChannelFeeConfig, ChannelSettings, ChannelSubscription, CrmSettings, Entity, Header, Notification, OptOutEntry, PaymentOrder, PeId, PlatformGeneralSettings, PlatformRazorpaySettings, PlatformSmsSettings, PlatformTurnstileSettings, PlatformWabaSettings, PlatformWallet, PlatformWalletTransaction, RateCard, RateCardSlab, RoutePolicy, Template, User, UserRateCard, UserRole, UserStatus, WabaConnection, WabaWallet, Wallet, WalletTransaction, Status
from .security import decrypt_secret, hash_api_key

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def save_upload(upload: UploadFile, subdir: str) -> tuple[str, bytes]:
    """Shared by every KYC/certificate-style upload across the app (DLT documents, PE
    certificates, and the company GST certificate) -- extension allowlist, size cap, and always a
    uuid4()-generated stored filename (never the user-supplied one, so there's no path-traversal
    or overwrite risk from a crafted filename)."""
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{ext}'. Allowed: PDF, JPG, PNG.")
    content = upload.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="File is too large (max 10MB).")
    directory = os.path.join(settings.uploads_dir, subdir)
    os.makedirs(directory, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{ext}"
    stored_path = os.path.join(directory, stored_name)
    with open(stored_path, "wb") as f:
        f.write(content)
    return stored_path, content


GST_RATE = 0.18

# Real GST SAC (Services Accounting Code) classification, as provided by the business's own
# accountant -- three item groups, not one per Invoice.type: "SMS Service" covers SMS wallet
# credit (self-service recharge or an admin's manual credit); "Platform Fee (DLT Registration
# Service)" and "Platform Fee (WhatsApp Business Platform Fee)" split the two platform-fee invoice
# types into their own Zoho line items (for the business's own reporting) while sharing the same
# SAC code. Used both for Textzi's own local PDF fallback (invoicing.py) and for the Zoho Books
# item mapping (zoho_books.py -- three Zoho Items total, named after these same groups). Lives
# here (not invoicing.py, where it's also used) so zoho_books.py can import it too without a cycle
# (invoicing.py -> zoho_books.py already exists the other way).
SAC_CODE_SMS_SERVICE = "998413"
SAC_CODE_PLATFORM_FEE = "998314"
SAC_CODE_CRM_QUOTE = "998399"
INVOICE_TYPE_ITEM_GROUP = {
    "wallet_recharge": "sms_service",
    "admin_credit": "sms_service",
    "dlt_fee": "platform_fee_dlt",
    "channel_subscription": "platform_fee_whatsapp",
    "crm_quote": "crm_quote",
}
ITEM_GROUP_SAC_CODES = {
    "sms_service": SAC_CODE_SMS_SERVICE,
    "platform_fee_dlt": SAC_CODE_PLATFORM_FEE,
    "platform_fee_whatsapp": SAC_CODE_PLATFORM_FEE,
    "crm_quote": SAC_CODE_CRM_QUOTE,
}
ITEM_GROUP_LABELS = {
    "sms_service": "SMS Service",
    "platform_fee_dlt": "Platform fee (DLT Registration Service)",
    "platform_fee_whatsapp": "Platform fee (WhatsApp Business Platform Fee)",
    "crm_quote": "CRM Quote",
}


def sac_code_for_invoice_type(invoice_type: str) -> str:
    group = INVOICE_TYPE_ITEM_GROUP.get(invoice_type)
    return ITEM_GROUP_SAC_CODES.get(group, SAC_CODE_SMS_SERVICE)

# Standard GST jurisdiction state codes (the first two digits of any GSTIN) -- used to derive a
# customer's state from their GSTIN for interstate (IGST) vs intrastate (CGST+SGST) determination
# in zoho_books.py, and to populate the State dropdown shown to organizations with no GSTIN.
GST_STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}


def state_code_from_gstin(gstin: str | None) -> str | None:
    """The first two digits of a GSTIN are its GST jurisdiction state code -- authoritative and
    always present whenever a GSTIN is, so this is preferred over any separately-captured state
    whenever a GSTIN is on file."""
    if not gstin or len(gstin) < 2:
        return None
    prefix = gstin[:2]
    return prefix if prefix in GST_STATE_CODES else None


@dataclass
class PlatformCompanyInfo:
    company_name: str
    company_address: str
    company_gstin: str
    company_state: str
    company_state_code: str
    company_phone: str
    support_email: str
    public_api_base_url: str


def get_platform_company_info(db: Session) -> PlatformCompanyInfo:
    """Resolves the DB-backed, admin-UI-editable PlatformGeneralSettings row, falling back
    field-by-field to the .env defaults in config.py wherever the admin hasn't set one -- so a
    deployment that never touches this settings page behaves identically to before it existed."""
    row = db.get(PlatformGeneralSettings, "platform")
    return PlatformCompanyInfo(
        company_name=(row.company_name if row and row.company_name else settings.company_name),
        company_address=(row.company_address if row and row.company_address else settings.company_address),
        company_gstin=(row.company_gstin if row and row.company_gstin else settings.company_gstin),
        company_state=(row.company_state if row and row.company_state else settings.company_state),
        company_state_code=(row.company_state_code if row and row.company_state_code else settings.company_state_code),
        company_phone=(row.company_phone if row and row.company_phone else settings.company_phone),
        support_email=(row.support_email if row and row.support_email else settings.support_email),
        public_api_base_url=(row.public_api_base_url if row and row.public_api_base_url else settings.public_api_base_url),
    )


_TURNSTILE_SECRET_UNCONFIGURED = "development-turnstile-secret-change-me"


def get_platform_turnstile_settings(db: Session) -> tuple[str, str | None]:
    """Resolves the DB-backed, admin-UI-editable PlatformTurnstileSettings row, falling back
    field-by-field to the .env defaults in config.py wherever the admin hasn't set one -- same
    convention as get_platform_company_info above. Returns (site_key, secret); secret is None if
    neither the DB row nor .env has ever been set to a real (non-placeholder) value, which
    turnstile.py treats as "unconfigured"."""
    row = db.get(PlatformTurnstileSettings, "platform")
    site_key = row.site_key if row and row.site_key else settings.turnstile_site_key
    if row and row.secret_key_encrypted:
        secret = decrypt_secret(row.secret_key_encrypted)
    elif settings.turnstile_secret != _TURNSTILE_SECRET_UNCONFIGURED:
        secret = settings.turnstile_secret
    else:
        secret = None
    return site_key, secret


def get_platform_waba_settings(db: Session) -> tuple[str | None, str | None, str | None]:
    """Resolves the admin-UI-editable PlatformWabaSettings row -- unlike Turnstile there's no
    .env fallback (no sensible placeholder Meta App ID exists), this is purely DB-configured.
    Returns (app_id, config_id, app_secret); all three are None until an admin has actually
    filled in Platform Settings > WhatsApp Setting."""
    row = db.get(PlatformWabaSettings, "platform")
    if not row:
        return None, None, None
    secret = decrypt_secret(row.app_secret_encrypted) if row.app_secret_encrypted else None
    return row.app_id, row.config_id, secret


def get_platform_razorpay_keys(db: Session) -> tuple[str | None, str | None]:
    """Resolves the DB-backed, admin-UI-editable PlatformRazorpaySettings row, falling back
    field-by-field to the .env defaults in config.py wherever the admin hasn't set one -- same
    convention as get_platform_company_info/get_platform_turnstile_settings above. Returns
    (key_id, key_secret); both are None if neither the DB row nor .env has ever been set, which
    every existing call site already treats as "Razorpay unconfigured" (see
    payments.py/channel_billing.py/channels.py/admin.py's own `if not key_id or not key_secret`
    guards -- unchanged by this helper's introduction)."""
    row = db.get(PlatformRazorpaySettings, "platform")
    key_id = row.key_id if row and row.key_id else settings.razorpay_key_id
    key_secret = decrypt_secret(row.key_secret_encrypted) if row and row.key_secret_encrypted else settings.razorpay_key_secret
    return key_id, key_secret


def get_platform_waba_webhook_verify_token(db: Session) -> str | None:
    """The value stored to compare against Meta's hub.verify_token GET handshake -- kept
    separate from get_platform_waba_settings's return tuple so the many existing call sites
    (connect flow, admin settings/test-connection) don't all need a 4th unused element."""
    row = db.get(PlatformWabaSettings, "platform")
    if not row or not row.webhook_verify_token_encrypted:
        return None
    return decrypt_secret(row.webhook_verify_token_encrypted)


def waba_webhook_url(db: Session) -> str | None:
    """The single, app-level callback URL every customer's WABA events arrive on -- registered
    once with Meta (App Dashboard > WhatsApp > Configuration), not per customer; the incoming
    payload's own phone_number_id is what tells waba_webhooks.py which customer a given event
    belongs to."""
    base_url = get_platform_company_info(db).public_api_base_url
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/v1/webhooks/waba"


def ttbs_webhook_url(db: Session, webhook_secret: str) -> str | None:
    """The URL Tata's DR callback should hit -- carries its own auth token in the query string,
    since we control this URL entirely and don't depend on TTBS sending any particular header.
    None while public_api_base_url isn't configured -- DR simply isn't requested in that case.
    Lives here (not provider_routes.py, where it's also used) because dispatch.py needs it too,
    and provider_routes.py -> admin.py -> auth.py -> dispatch.py would otherwise be a cycle."""
    base_url = get_platform_company_info(db).public_api_base_url
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/v1/webhooks/ttbs/dr?token={webhook_secret}"


def client_ip(request: Request) -> str | None:
    """request.client.host is always the reverse proxy's own address when this API sits behind
    one (Cloudflare + Coolify's Traefik in production), which silently defeats the API-key IP
    allow-list -- either rejecting every legitimate call, or once "fixed" by allow-listing the
    proxy's IP, accepting traffic from anywhere. This is opt-in via settings.trust_proxy_headers
    rather than trusted by default.

    CF-Connecting-IP is checked first, ahead of X-Forwarded-For: Cloudflare's edge always sets
    this header itself to the IP it actually terminated the TCP connection from, and does not
    honor/forward a client-supplied value for it -- unlike X-Forwarded-For, which Cloudflare (like
    most proxies) only ever APPENDS to, preserving whatever a client already put in it. That means
    `X-Forwarded-For.split(",")[0]` is spoofable by any caller simply sending their own fabricated
    X-Forwarded-For -- with a real request through Cloudflare, no bypass needed -- which would
    defeat the IP allow-list this feeds today. Falls back to X-Forwarded-For only when
    CF-Connecting-IP is absent (a non-Cloudflare proxy in front, e.g. local dev). This still
    doesn't stop a caller who reaches the origin directly, bypassing Cloudflare's edge entirely --
    that requires a network-layer control (a firewall/security-group rule restricting inbound
    traffic to Cloudflare's published IP ranges, or Cloudflare's Authenticated Origin Pulls
    feature) outside this application's own reach."""
    if settings.trust_proxy_headers:
        cf_connecting_ip = request.headers.get("CF-Connecting-IP")
        if cf_connecting_ip:
            return cf_connecting_ip.strip()
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def parse_user_agent(user_agent: str | None) -> tuple[str | None, str | None, str | None]:
    """Coarse (browser, os, device_type) from a User-Agent string -- deliberately simple regex
    matching rather than a full UA-parsing library/database, since visitor analytics only ever
    needs "Chrome / Windows / desktop"-level detail, not exact version/build numbers."""
    if not user_agent:
        return None, None, None
    ua = user_agent

    if "Edg/" in ua or "Edge/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "CriOS" in ua:
        browser = "Chrome (iOS)"
    elif "Chrome/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua and "Version/" in ua:
        browser = "Safari"
    else:
        browser = "Other"

    if "Windows" in ua:
        os_name = "Windows"
    elif "Mac OS X" in ua and "Mobile" not in ua:
        os_name = "macOS"
    elif "Android" in ua:
        os_name = "Android"
    elif "iPhone" in ua or "iPad" in ua or "iOS" in ua:
        os_name = "iOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Other"

    if "iPad" in ua or "Tablet" in ua:
        device_type = "tablet"
    elif "Mobile" in ua or "Android" in ua or "iPhone" in ua:
        device_type = "mobile"
    else:
        device_type = "desktop"

    return browser, os_name, device_type


class DomainError(Exception):
    pass


class AuthenticationError(DomainError):
    """The caller's credentials themselves are invalid/unrecognized -- maps to HTTP 401."""
    pass


class AuthorizationError(DomainError):
    """The caller is recognized but not allowed to do this -- maps to HTTP 403."""
    pass


class RateLimitError(DomainError):
    """Caller is over the allowed request rate -- maps to HTTP 429."""
    pass


class OptedOutError(DomainError):
    """Recipient is on this entity's own opt-out list -- maps to HTTP 422, same as any other
    send-time validation failure (never billed, never dispatched)."""
    pass


# 3GPP TS 23.038 GSM 7-bit default alphabet (basic character set) -- a message using only these
# characters is billed on the GSM-7 boundaries (160 single-segment / 153 per segment once
# concatenated). Any character outside this set (emoji, most non-Latin scripts, smart quotes,
# em-dashes, ...) forces the WHOLE message to Unicode/UCS-2, which carriers bill on much
# narrower boundaries (70 single-segment / 67 per segment) -- confirmed against real carrier
# billing behavior, not just this codebase's own prior (incorrect) assumption that every message
# is 160/153 regardless of content.
GSM7_BASIC_SET = set(
    "@£$¥èéùìòÇ\nØø\rÅå"
    "Δ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà",
)
# These are valid GSM-7 characters too, but each needs an escape character (0x1B) ahead of it,
# so it counts as 2 characters of message length, not 1 -- matching how carriers actually count
# extended-table characters toward the 160/153 boundary.
GSM7_EXTENDED_SET = set("^{}\\[~]|€")

GSM7_SINGLE_SEGMENT_LENGTH = 160
GSM7_CONCAT_SEGMENT_LENGTH = 153
UCS2_SINGLE_SEGMENT_LENGTH = 70
UCS2_CONCAT_SEGMENT_LENGTH = 67


def _is_gsm7_encodable(body: str) -> bool:
    return all(ch in GSM7_BASIC_SET or ch in GSM7_EXTENDED_SET for ch in body)


def _gsm7_character_count(body: str) -> int:
    return sum(2 if ch in GSM7_EXTENDED_SET else 1 for ch in body)


def _ucs2_code_unit_count(body: str) -> int:
    """UCS-2/SMS billing counts UTF-16 code units, not Python codepoints -- a character outside
    the Basic Multilingual Plane (most emoji, e.g. U+1F600) needs a surrogate pair and counts as
    2 units, but Python's len() counts it as 1 codepoint. encode('utf-16-le') then halving the
    byte length gives the real code-unit count regardless of that gap (confirmed: 10 emoji
    measured as 20 UTF-16 code units this way, matching what a real carrier bills, not the 10
    Python's len() alone would suggest)."""
    return len(body.encode("utf-16-le")) // 2


def sms_segment_credits(body: str) -> int:
    """1 credit per SMS segment, rounded up -- but the segment boundary itself depends on the
    message's encoding, not a flat 160 chars for everything. A message using only GSM-7 default-
    alphabet characters is billed at 160 chars for a single segment / 153 per segment once it
    needs to be concatenated across multiple parts. Any other character (emoji, most non-Latin
    scripts, curly quotes, em-dashes, ...) forces the entire message into Unicode/UCS-2 encoding,
    which is billed at a much narrower 70 chars single-segment / 67 per segment -- billing every
    message on the GSM-7 boundary regardless of content undercharged non-GSM-7 messages by
    3-6x versus what a real carrier actually bills. Minimum 1 credit even for an empty body."""
    if not body:
        return 1
    if _is_gsm7_encodable(body):
        length = _gsm7_character_count(body)
        if length <= GSM7_SINGLE_SEGMENT_LENGTH:
            return 1
        return -(-length // GSM7_CONCAT_SEGMENT_LENGTH)  # ceiling division
    length = _ucs2_code_unit_count(body)
    if length <= UCS2_SINGLE_SEGMENT_LENGTH:
        return 1
    return -(-length // UCS2_CONCAT_SEGMENT_LENGTH)  # ceiling division


def normalize_mobile(mobile: str) -> str:
    """Canonical form used only for opt-out/consent comparison -- strips a leading '91'
    country-code prefix when what's left is a plausible 10-digit Indian mobile number, so
    '919000009999' and '9000009999' (the same physical subscriber, just two equally
    schema-valid ways to write the same number) always compare equal. Storage/display of the
    mobile everywhere else in the system is untouched by this -- it exists purely so the opt-out
    list can't be trivially bypassed by re-formatting a number that was already suppressed."""
    digits = mobile.strip()
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return digits[2:]
    return digits


def assert_not_opted_out(db: Session, entity_id: str, mobile: str) -> None:
    target = normalize_mobile(mobile)
    entries = db.scalars(select(OptOutEntry).where(OptOutEntry.entity_id == entity_id)).all()
    if any(normalize_mobile(entry.mobile) == target for entry in entries):
        raise OptedOutError(f"Recipient {mobile} has opted out of messages from this account")


_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is None:
        import redis as redis_lib
        _redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    return _redis_client


def enforce_rate_limit(key: str, max_requests: int, window_seconds: int, amount: int = 1) -> None:
    """Fixed-window request counter backed by Redis -- shared across every API process/replica,
    unlike an in-process counter (which resets per worker and under-counts abuse spread across
    them behind a load balancer). Fails OPEN (never blocks a send) if Redis itself is unreachable
    -- a rate limiter that can take down the whole send path on a Redis blip would be worse than
    one that's occasionally permissive during an outage.

    `amount` lets a single call consume more than one unit of budget -- main.py's send_sms_bulk
    passes len(recipients) so a 100-recipient batch counts as 100 messages against the same
    window a single send would, instead of the whole batch costing 1 unit and letting bulk send
    up to max_requests * 100 actual messages per window versus max_requests for single sends."""
    import redis as redis_lib
    try:
        client = _redis()
        count = client.incrby(key, amount)
        if count == amount:
            client.expire(key, window_seconds)
        if count > max_requests:
            raise RateLimitError(f"Rate limit exceeded: max {max_requests} requests per {window_seconds}s")
    except redis_lib.RedisError:
        return


def resolve_entity_from_key(db: Session, api_key: str, client_ip: str | None = None) -> Entity:
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(api_key), ApiKey.active == True))  # noqa: E712
    if not key:
        raise AuthenticationError("Invalid API key")
    if key.allowed_ips and client_ip not in key.allowed_ips:
        raise AuthorizationError("Request blocked: caller IP is not on this API key's allow-list")
    entity = db.get(Entity, key.entity_id)
    if not entity or entity.status != Status.active:
        raise AuthorizationError("Entity is not active")
    return entity


def resolve_template(db: Session, entity_id: str, alias: str) -> Template:
    template = db.scalar(select(Template).where(Template.entity_id == entity_id, Template.alias == alias, Template.status == Status.active))
    if not template:
        raise DomainError(f"Template alias '{alias}' is not approved for this entity")
    pe = db.get(PeId, template.pe_id)
    header = db.get(Header, template.header_id)
    if not pe or pe.status != Status.active or not header or header.status != Status.active:
        raise DomainError("Template DLT mapping is not fully approved")
    return template


def resolve_template_by_dlt_id(db: Session, entity_id: str, dlt_template_id: str) -> Template:
    """Same as resolve_template, keyed by the DLT-registered template id instead of Textzi's own
    alias -- used by the external API (main.py's send_sms/send_sms_bulk), where the caller
    already tracks their own registered template ids and sends the complete message text
    themselves rather than variables for Textzi to interpolate."""
    template = db.scalar(select(Template).where(Template.entity_id == entity_id, Template.dlt_template_id == dlt_template_id, Template.status == Status.active))
    if not template:
        raise DomainError(f"DLT template id '{dlt_template_id}' is not approved for this entity")
    pe = db.get(PeId, template.pe_id)
    header = db.get(Header, template.header_id)
    if not pe or pe.status != Status.active or not header or header.status != Status.active:
        raise DomainError("Template DLT mapping is not fully approved")
    return template


def validate_template_body(body: str) -> None:
    """Rejects a template that mixes Textzi's own {{var}} convention with the DLT platform's own
    {#...#} convention in the same body. render_template (below) handles each correctly in
    isolation, but not together: its {#...#} pass pulls positionally from the *entire* variables
    dict in insertion order, with no awareness of which entries the {{var}} pass already consumed
    by name -- so a mixed template could silently substitute the wrong value into a real
    placeholder (e.g. an OTP field getting a name instead of the code), with no error, just wrong
    content going to the recipient. Enforced at save time so this ambiguous case can never be
    stored, rather than risking it at send time."""
    has_named = bool(re.search(r"\{\{\s*\w+\s*\}\}", body))
    has_dlt = bool(re.search(r"\{#[^{}]*#\}", body))
    if has_named and has_dlt:
        raise DomainError("Template body mixes {{var}} and {#...#} placeholder styles -- use exactly one convention, not both.")


def render_template(body: str, variables: dict[str, str]) -> str:
    def substitute(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            raise DomainError(f"Missing template variable '{key}'")
        return variables[key]
    result = re.sub(r"\{\{\s*(\w+)\s*\}\}", substitute, body)

    # DLT-registered templates use {#var#}-style placeholders (the TRAI/DLT platform's own
    # convention -- every operator-approved template uses this, not Textzi's {{var}}), which was
    # never matched here at all -- confirmed live, a real template shipped the literal text
    # "{#num#}" to the recipient's phone instead of the actual code. DLT itself treats these
    # purely positionally (the registry doesn't care what name is written inside the braces, only
    # how many slots exist and in what order), so each {#...#} is filled in sequence from the same
    # variables dict, by value order rather than by matching the name inside the braces to a key.
    dlt_values = iter(variables.values())

    def substitute_dlt(_match: re.Match) -> str:
        try:
            return next(dlt_values)
        except StopIteration:
            raise DomainError("Template has more {#...#} placeholders than variables provided")
    return re.sub(r"\{#[^{}]*#\}", substitute_dlt, result)


def _wallet_available_decimal(wallet: Wallet | WabaWallet) -> Decimal:
    return wallet.prepaid_balance + max(Decimal(0), wallet.credit_limit - wallet.credit_used)


def _wallet_available(wallet: Wallet | WabaWallet) -> float:
    return float(_wallet_available_decimal(wallet))


def available_balance(db: Session, entity_id: str, wallet_model: type[Wallet] | type[WabaWallet] = Wallet) -> float:
    wallet = db.get(wallet_model, entity_id)
    if not wallet:
        raise DomainError("Wallet is not configured")
    return _wallet_available(wallet)


def credit_wallet(db: Session, entity_id: str, amount: float, transaction_type: str, reference: str | None = None, wallet_model: type[Wallet] | type[WabaWallet] = Wallet, channel: str = "sms") -> Wallet | WabaWallet:
    """Adds `amount` (must be positive) to the wallet's prepaid balance and records a ledger
    entry. Row-locked (SELECT ... FOR UPDATE) so two concurrent credits/debits on the same
    wallet serialize instead of both reading a stale balance and losing an update; math is done
    in Decimal (via str(amount), never Decimal(amount) directly, to avoid importing amount's own
    binary-float artifacts) rather than float to avoid ledger drift across many transactions."""
    if amount <= 0:
        raise DomainError("Credit amount must be positive")
    wallet = db.get(wallet_model, entity_id, with_for_update=True)
    if not wallet:
        raise DomainError("Wallet is not configured")
    amount_dec = Decimal(str(amount))
    wallet.prepaid_balance = wallet.prepaid_balance + amount_dec
    # balance_after is a ledger snapshot, not the wallet's own balance -- must stay Decimal all
    # the way to the column (_wallet_available_decimal), not _wallet_available's float cast, or
    # this one field picks up binary-float rounding noise the rest of this function deliberately
    # avoids.
    db.add(WalletTransaction(entity_id=entity_id, channel=channel, type=transaction_type, amount=amount_dec, balance_after=_wallet_available_decimal(wallet), reference=reference))
    return wallet


def debit_wallet(db: Session, entity_id: str, amount: float, reference: str | None = None, wallet_model: type[Wallet] | type[WabaWallet] = Wallet, channel: str = "sms") -> Wallet | WabaWallet:
    """Deducts `amount` (must be positive), spending prepaid balance first and then credit
    headroom, and records a signed (negative) ledger entry. Row-locked like credit_wallet."""
    if amount <= 0:
        raise DomainError("Debit amount must be positive")
    wallet = db.get(wallet_model, entity_id, with_for_update=True)
    if not wallet:
        raise DomainError("Wallet is not configured")
    amount_dec = Decimal(str(amount))
    if _wallet_available_decimal(wallet) < amount_dec:
        raise DomainError("Insufficient wallet balance or credit")
    prepaid = wallet.prepaid_balance
    from_prepaid = min(prepaid, amount_dec)
    wallet.prepaid_balance = prepaid - from_prepaid
    remaining = amount_dec - from_prepaid
    if remaining > 0:
        wallet.credit_used = wallet.credit_used + remaining
    db.add(WalletTransaction(entity_id=entity_id, channel=channel, type="debit", amount=-amount_dec, balance_after=_wallet_available_decimal(wallet), reference=reference))
    return wallet


TOPUP_MISMATCH_TOLERANCE = 0.01  # rupee-level float rounding noise, not a real discrepancy


def expected_topup_credits(order: PaymentOrder) -> float | None:
    """Recomputes what a paid order's credits *should* be, independently of whatever was actually
    applied to the wallet -- from the order's own snapshotted amount/price_per_sms (set server-side
    at order-creation, see payments.create_order), never from anything client-supplied. Returns
    None for a legacy order with no snapshotted rate (nothing to reconcile against)."""
    if not order.price_per_sms:
        return None
    return float(order.amount) / float(order.price_per_sms)


def enforce_topup_integrity(db: Session, order: PaymentOrder, entity: Entity, user: User, actual_credits: float) -> bool:
    """Called immediately after a wallet top-up is credited (payments.verify_payment) and again
    across history by the admin reconciliation report (admin.wallet_topup_report) -- same check,
    two callers. Compares the credits actually applied against what the order's own snapshotted
    rate says they should be; under the current design these can only diverge from a future code
    change that credits a different value than what was quoted (see PaymentOrder.credits_applied),
    not from anything a client can influence today, but this is the safety net for exactly that
    "someone edited this code and broke the invariant" case.

    On mismatch: suspends the account, deactivates every API key on the entity, logs it, and
    emails the platform's support address -- immediately, not just flagged for later review, per
    explicit instruction that a detected mismatch must block the account and API right away."""
    expected = expected_topup_credits(order)
    if expected is None or abs(expected - actual_credits) <= TOPUP_MISMATCH_TOLERANCE:
        return False

    user.status = UserStatus.suspended
    for key in db.scalars(select(ApiKey).where(ApiKey.entity_id == entity.id, ApiKey.active == True)).all():  # noqa: E712
        key.active = False
    log_activity(
        db, entity.organization_id, "wallet_topup_mismatch_blocked",
        f"Wallet top-up credit mismatch on order {order.id}: expected {expected:.2f} credits, {actual_credits:.2f} applied. "
        f"Account suspended and all API keys deactivated.",
        user_id=user.id, actor_email=user.email,
    )
    info = get_platform_company_info(db)
    send_email(
        db, to=info.support_email,
        subject=f"[Security] Wallet top-up mismatch -- {user.email} blocked",
        html_body=render_email(
            "Wallet top-up credit mismatch detected",
            f"<p>Order <strong>{order.id}</strong> (entity {entity.id}, user {user.email}) credited "
            f"<strong>{actual_credits:.2f}</strong> credits but the order's own quoted rate expected "
            f"<strong>{expected:.2f}</strong>.</p>"
            f"<p>The account has been suspended and every API key on this entity deactivated automatically. "
            f"Investigate before reinstating.</p>",
        ),
    )
    return True


def expected_order_paise(order: PaymentOrder) -> int:
    """The paise amount Razorpay should have actually captured for this order, computed the same
    way it was at order-creation time (payments.create_order / channels.create_dlt_request_order)
    -- wallet recharges are grossed up by GST at checkout, DLT request fees are not (their
    total_amount is already GST-inclusive when the order is created)."""
    if order.purpose == "dlt_request":
        return int(round(float(order.amount) * 100))
    return int(round(float(order.amount) * (1 + GST_RATE) * 100))


def flag_suspicious_payment(db: Session, order: PaymentOrder, entity: Entity, reason: str, user: User | None = None) -> None:
    """Called when Razorpay's own record of a payment -- fetched independently here, never trusted
    from what the client reports back after checkout -- doesn't match what this order expects
    (wrong captured amount, or never actually captured). Flags the order for manual admin review
    only: does NOT credit the wallet, issue an invoice, or touch the account/API keys, since a
    mismatch could be a legitimate edge case and not necessarily fraud. Contrast
    enforce_topup_integrity, which suspends the account immediately -- that guards a different,
    code-only invariant (the codebase's own math against itself), not anything Razorpay-side."""
    order.status = "suspicious"
    log_activity(
        db, entity.organization_id, "payment_flagged_suspicious",
        f"Payment order {order.id} flagged suspicious: {reason}",
        user_id=user.id if user else None, actor_email=user.email if user else None,
    )
    info = get_platform_company_info(db)
    send_email(
        db, to=info.support_email,
        subject=f"[Review] Payment order {order.id} flagged suspicious",
        html_body=render_email(
            "Payment amount could not be automatically confirmed",
            f"<p>Order <strong>{order.id}</strong> (entity {entity.id}) was flagged suspicious: {reason}</p>"
            f"<p>No wallet credit or invoice was issued. Verify manually via Razorpay's own dashboard, then use "
            f"the admin wallet-credit tool if the payment turns out to be legitimate.</p>",
        ),
    )


def resolve_rate_card(db: Session, user: User) -> RateCard:
    assignment = db.get(UserRateCard, user.id)
    if assignment:
        card = db.get(RateCard, assignment.rate_card_id)
        if card:
            return card
    card = db.scalar(select(RateCard).where(RateCard.is_default == True, RateCard.channel == "sms"))  # noqa: E712
    if not card:
        raise DomainError("No default rate card is configured")
    return card


def rate_card_slabs(db: Session, rate_card_id: str) -> list[RateCardSlab]:
    return list(db.scalars(select(RateCardSlab).where(RateCardSlab.rate_card_id == rate_card_id).order_by(RateCardSlab.min_amount)).all())


def quote_credits(db: Session, rate_card: RateCard, amount: float) -> tuple[float, RateCardSlab]:
    """How many SMS credits `amount` (pre-GST rupees) buys under this rate card. Slabs price by
    the rupee amount of the recharge itself -- e.g. Rs.1-1000 recharged buys credits at
    Rs.0.25/SMS, Rs.1001-3000 at Rs.0.23/SMS -- so a bigger top-up unlocks a cheaper rate."""
    slabs = rate_card_slabs(db, rate_card.id)
    if not slabs:
        raise DomainError("This rate card has no slabs configured")
    for slab in slabs:
        if amount >= float(slab.min_amount) and (slab.max_amount is None or amount <= float(slab.max_amount)):
            return amount / float(slab.price_per_sms), slab
    last = slabs[-1]
    return amount / float(last.price_per_sms), last


def require_min_recharge(rate_card: RateCard, amount: float) -> None:
    if amount < float(rate_card.min_recharge_amount):
        raise DomainError(f"Minimum top-up for the '{rate_card.name}' plan is Rs.{float(rate_card.min_recharge_amount):.2f}")


def resolve_user_entity(db: Session, user: User) -> Entity:
    if not user.organization_id:
        raise DomainError("Complete organisation onboarding before accessing wallet features")
    entity = db.scalar(select(Entity).where(Entity.organization_id == user.organization_id))
    if not entity:
        raise DomainError("No entity found for this organization")
    return entity


def resolve_primary_user(db: Session, organization_id: str) -> User | None:
    """The earliest-created user in an organization -- used as the "primary contact" for
    invoice delivery and rate-card resolution when an action targets an entity/org rather than
    a specific logged-in user (e.g. admin manual wallet credit)."""
    return db.scalar(select(User).where(User.organization_id == organization_id).order_by(User.created_at.asc()))


def log_activity(db: Session, organization_id: str | None, event_type: str, description: str, user_id: str | None = None, actor_email: str | None = None, ip_address: str | None = None, request: Request | None = None) -> None:
    """Writes one Activity Log row. organization_id may legitimately be None -- platform-staff
    accounts have no organization at all, so their own logins/actions (and org-agnostic admin
    mutations like a rate card change) still get recorded, just filed under the cross-org admin
    audit log (GET /v1/admin/audit-log) instead of any single customer's Reports > Activity Log.

    Pass `request` (not just `ip_address`) wherever the caller has it -- it derives both IP and
    User-Agent in one go via client_ip()/the same header this project already trusts for
    UserSession (see auth.py's _create_session), so every event carries the same device/browser
    telemetry already shown on the Sessions page instead of just an IP."""
    resolved_ip = ip_address if ip_address is not None else (client_ip(request) if request else None)
    user_agent = request.headers.get("user-agent", "")[:300] if request else None
    db.add(AccountActivity(organization_id=organization_id, user_id=user_id, actor_email=actor_email or "", event_type=event_type, description=description, ip_address=resolved_ip, user_agent=user_agent))


ALL_CAPABILITIES = {"wallet:recharge", "channels:manage", "invoices:view", "team:invite", "team:view", "activity:view"}

ROLE_CAPABILITIES: dict[str, set[str]] = {
    # activity:view (org-wide login/security history across every teammate) is deliberately not
    # granted to any of the internal sub-roles below -- it's account-owner-only, unlike
    # team:view/invoices:view which every sub-role gets for visibility into their own org.
    UserRole.enterprise_customer.value: {"wallet:recharge", "channels:manage", "invoices:view", "team:invite", "team:view", "activity:view"},
    UserRole.sub_user.value: {"wallet:recharge", "channels:manage", "invoices:view", "team:view"},
    UserRole.finance_user.value: {"wallet:recharge", "invoices:view", "team:view"},
    UserRole.marketing_user.value: {"channels:manage", "team:view"},
    UserRole.read_only_user.value: {"invoices:view", "team:view"},
    # Internal-only roles: their real boundaries were never specified, so they keep today's
    # pre-existing full access rather than having a restriction invented for them here -- but
    # listed explicitly now (not via a fallback) so an unrecognized/mistyped/future role can
    # never silently inherit this by accident (see the fail-closed default below).
    UserRole.developer.value: ALL_CAPABILITIES,
    UserRole.finance_team.value: ALL_CAPABILITIES,
    UserRole.support_team.value: ALL_CAPABILITIES,
    UserRole.sales_team.value: ALL_CAPABILITIES,
    UserRole.reseller.value: ALL_CAPABILITIES,
    UserRole.agency.value: ALL_CAPABILITIES,
}


def capabilities_for(role: str) -> set[str]:
    """Fails closed: any role string not explicitly listed (a typo, a future enum value nobody
    updated this dict for) gets zero capabilities rather than silently inheriting full access."""
    if role in ADMIN_ROLES:
        return {"*"}
    return ROLE_CAPABILITIES.get(role, set())


def has_capability(role: str, capability: str) -> bool:
    caps = capabilities_for(role)
    return "*" in caps or capability in caps


def get_platform_sms_settings(db: Session) -> PlatformSmsSettings | None:
    row = db.get(PlatformSmsSettings, "platform")
    if not row or not row.template_body or not row.sender_id:
        return None
    return row


def credit_platform_wallet(db: Session, amount: float, type: str, reference: str | None = None) -> PlatformWallet:
    if amount <= 0:
        raise DomainError("Credit amount must be positive")
    wallet = db.get(PlatformWallet, "platform", with_for_update=True)
    if not wallet:
        wallet = PlatformWallet(id="platform", balance=0)
        db.add(wallet)
        db.flush()
    amount_dec = Decimal(str(amount))
    wallet.balance = wallet.balance + amount_dec
    db.add(PlatformWalletTransaction(type=type, amount=amount_dec, balance_after=wallet.balance, reference=reference))
    return wallet


def debit_platform_wallet(db: Session, amount: float, type: str, reference: str | None = None) -> PlatformWallet | None:
    """Returns None (rather than raising) if the platform wallet is missing or underfunded --
    platform sending fails open to the existing log/dev-echo fallback rather than ever blocking
    a user's login on an internal balance problem. Row-locked like the tenant wallet functions."""
    wallet = db.get(PlatformWallet, "platform", with_for_update=True)
    amount_dec = Decimal(str(amount))
    if not wallet or wallet.balance < amount_dec:
        return None
    wallet.balance = wallet.balance - amount_dec
    db.add(PlatformWalletTransaction(type=type, amount=-amount_dec, balance_after=wallet.balance, reference=reference))
    return wallet


def resolve_channel_fees(db: Session, channel: str = "sms") -> ChannelFeeConfig:
    fees = db.get(ChannelFeeConfig, channel)
    if not fees:
        raise DomainError(f"No fee configuration exists for channel '{channel}'")
    return fees


def _channel_has_published_plans(db: Session, channel: str) -> bool:
    return db.scalar(select(BillingPlan).where(BillingPlan.channel == channel, BillingPlan.active.is_(True)).limit(1)) is not None


def _has_active_plan_subscription(db: Session, entity_id: str, channel: str) -> bool:
    subscription = db.get(ChannelSubscription, (entity_id, channel))
    return bool(subscription and subscription.plan_id and subscription.period_end and subscription.period_end > datetime.now(timezone.utc))


def channel_enabled(db: Session, channel: str) -> bool:
    """The global kill switch alone (ChannelFeeConfig.enabled), independent of any per-entity
    subscription/connection state -- usable standalone at points like "start connecting WABA"
    where the full channel_active() below can't apply yet (it wouldn't be connected until this
    very call succeeds, so channel_active("waba") would always read false beforehand)."""
    fees = db.get(ChannelFeeConfig, channel)
    return not (fees and not fees.enabled)


def channel_active(db: Session, entity_id: str, channel: str = "sms") -> bool:
    """A channel is active once its (possibly-zero) subscription price is paid and the entity
    has completed that channel's own activation requirement. For SMS/DLT-based channels, DLT
    approval is derived from PeId.status rather than a separate flag, so it can never drift out
    of sync with the actual DLT assets. WABA has no DLT concept at all -- reusing the PE ID check
    for it (the previous behavior) reported "WABA active" for any customer who merely had SMS DLT
    active, which was never actually true; WABA's own readiness signal is a connected
    WabaConnection instead.

    WABA/CRM additionally require an active BillingPlan subscription (see
    ChannelSubscription.plan_id/period_end and channel_billing.py) -- but only once that channel
    actually has at least one published plan. Before any plan exists for a channel, it stays on
    the older free/connection-only gate below, so introducing a plan catalog doesn't retroactively
    lock out every entity that was already using the channel for free.

    channel_enabled() (the global kill switch) is checked first, unconditionally -- overriding
    every per-entity subscription/connection check below. See its own docstring and
    ChannelFeeConfig's model docstring."""
    if not channel_enabled(db, channel):
        return False
    fees = db.get(ChannelFeeConfig, channel)
    subscription_price = float(fees.subscription_price) if fees else 0
    if subscription_price > 0:
        subscription = db.get(ChannelSubscription, (entity_id, channel))
        if not subscription or not subscription.paid_at:
            return False
    if channel == "waba":
        connection = db.get(WabaConnection, entity_id)
        if not connection or connection.status != "connected":
            return False
        if _channel_has_published_plans(db, "waba"):
            return _has_active_plan_subscription(db, entity_id, "waba")
        return True
    if channel == "crm":
        if _channel_has_published_plans(db, "crm"):
            return _has_active_plan_subscription(db, entity_id, "crm")
        # No external connection step like WABA's Embedded Signup, and no plan published yet --
        # the subscription-paid check above (or a zero price) is the whole readiness bar.
        return True
    has_active_pe = db.scalar(select(PeId).where(PeId.entity_id == entity_id, PeId.status == Status.active).limit(1)) is not None
    return has_active_pe


def require_channel_active(db: Session, entity_id: str, channel: str = "sms") -> None:
    if not channel_active(db, entity_id, channel):
        raise DomainError(f"Activate the {channel.upper()} channel (complete DLT registration) before using this feature")


def notify_user(db: Session, entity_id: str, user_id: str, notif_type: str, title: str, body: str, link: str | None = None) -> None:
    """Creates the in-app Notification row (always), and additionally emails the user if this
    entity's CrmSettings.notify_email is on. SMS/WhatsApp aren't sent here -- see Notification's
    own docstring for why (no DLT/template registration to send arbitrary text through yet)."""
    db.add(Notification(entity_id=entity_id, user_id=user_id, type=notif_type, title=title, body=body, link=link))
    settings_row = db.get(CrmSettings, entity_id)
    if settings_row and settings_row.notify_email:
        user = db.get(User, user_id)
        if user and user.email:
            send_email(db, user.email, title, render_email(title, f"<p>{body}</p>"))


def check_message_quota(db: Session, entity_id: str, channel: str) -> None:
    """Hard-blocks a send once the entity's active plan's message_limit is reached -- a no-op if
    the channel has no plan-based subscription (no plan published, or plan has no message_limit
    set) since there's nothing to enforce. Call before sending; increment_message_usage after a
    successful send."""
    subscription = db.get(ChannelSubscription, (entity_id, channel))
    if not subscription or not subscription.plan_id:
        return
    plan = db.get(BillingPlan, subscription.plan_id)
    if not plan or not plan.message_limit:
        return
    if subscription.messages_used >= plan.message_limit:
        raise DomainError(f"This account has used all {plan.message_limit} messages included in its {plan.name} plan this billing period. Upgrade your plan to send more.")


def increment_message_usage(db: Session, entity_id: str, channel: str) -> None:
    subscription = db.get(ChannelSubscription, (entity_id, channel))
    if subscription and subscription.plan_id:
        subscription.messages_used += 1


def check_seat_quota(db: Session, organization_id: str) -> None:
    """Hard-blocks inviting a new team member once the org's headcount would exceed the tightest
    user_limit among its active plan-based channel subscriptions. Users aren't partitioned per
    channel in this codebase (one invite grants access to everything the org has), so the binding
    constraint is whichever active plan's seat limit is smallest."""
    entity = db.scalar(select(Entity).where(Entity.organization_id == organization_id))
    if not entity:
        return
    current_users = db.scalar(select(func.count()).select_from(User).where(User.organization_id == organization_id)) or 0
    for channel in ("waba", "crm"):
        subscription = db.get(ChannelSubscription, (entity.id, channel))
        if not subscription or not subscription.plan_id:
            continue
        plan = db.get(BillingPlan, subscription.plan_id)
        if not plan or not plan.user_limit:
            continue
        if current_users >= plan.user_limit:
            raise DomainError(f"This account has reached the {plan.user_limit}-user limit on its {plan.name} plan. Upgrade your plan to add more team members.")


def is_encryption_enabled(db: Session, entity_id: str, channel: str = "sms") -> bool:
    settings_row = db.get(ChannelSettings, (entity_id, channel))
    return bool(settings_row and settings_row.encryption_enabled)


def mask_mobile(mobile: str) -> str:
    """Keeps only the last 4 characters visible, e.g. 919876543210 -> XXXXXXXX3210."""
    if len(mobile) <= 4:
        return "X" * len(mobile)
    return "X" * (len(mobile) - 4) + mobile[-4:]


def mask_aadhar(aadhar: str) -> str:
    """Keeps only the last 4 digits visible, e.g. 123456789012 -> XXXXXXXX9012."""
    if len(aadhar) <= 4:
        return "X" * len(aadhar)
    return "X" * (len(aadhar) - 4) + aadhar[-4:]


def mask_email(email: str) -> str:
    """Keeps the first character of the local part and the whole domain visible, e.g.
    jane.doe@example.com -> j*******@example.com."""
    local, _, domain = email.partition("@")
    if not domain:
        return "*" * len(email)
    if len(local) <= 1:
        return f"{local}@{domain}"
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"


def redact_otp(text: str) -> str:
    """Digit runs of 4+ are almost certainly an OTP code -- redact before ever persisting or
    displaying platform OTP-send telemetry to an admin. The code is single-use and short-lived,
    but there's no reason an admin support view needs to see it at all."""
    return re.sub(r"\d{4,}", lambda m: "*" * len(m.group()), text)


def redact_payload_values(payload: dict | None, redactions: dict[str, str]) -> dict | None:
    """Recursively replaces any string value in `payload` that exactly matches a key in
    `redactions` with its corresponding replacement, at any nesting depth. Used to scrub plaintext
    message content/recipient out of provider request/response telemetry before it's persisted --
    by value rather than by field name, since a provider adapter's own field naming varies
    (TTBS's fixed "msg"/"recipient" vs. HttpsSmsProvider's admin-configurable param_mapping)."""
    if payload is None:
        return None

    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str) and value in redactions:
            return redactions[value]
        return value

    return walk(payload)


def resolve_routes(db: Session, user_id: str | None, user_group: str | None, entity_id: str | None = None) -> list[str]:
    """Checks policies from most to least specific: a named user, then a group, then the whole
    entity/account -- falling through each tier only if the more specific one has no policy set,
    not merely no ID supplied (a caller with no user_id at all, e.g. a backend integration with
    no per-user concept, still gets the entity-level policy applied via entity_id alone)."""
    if user_id:
        policy = db.scalar(select(RoutePolicy).where(RoutePolicy.subject_type == "user", RoutePolicy.subject_id == user_id, RoutePolicy.active == True))  # noqa: E712
        if policy:
            return policy.routes
    if user_group:
        policy = db.scalar(select(RoutePolicy).where(RoutePolicy.subject_type == "group", RoutePolicy.subject_id == user_group, RoutePolicy.active == True))  # noqa: E712
        if policy:
            return policy.routes
    if entity_id:
        policy = db.scalar(select(RoutePolicy).where(RoutePolicy.subject_type == "entity", RoutePolicy.subject_id == entity_id, RoutePolicy.active == True))  # noqa: E712
        if policy:
            return policy.routes
    return ["default-simulated-route"]


def resolve_user_route_policy(db: Session, user_id: str) -> list[str]:
    """The external API's own routing rule (main.py's send_sms/send_sms_via_url): user_id is
    mandatory there and already verified to belong to the caller's own organization before this is
    ever called, so routing is decided by that user's own Route Policy specifically -- entity-level
    policies are never consulted as an in-between tier here, unlike the dashboard's own
    resolve_routes (still used by sms.py's compose_sms). Never raises for a missing policy -- the
    admin simply not having set one up for this particular user falls back to the simulated route,
    same fallback constant resolve_routes uses; only the caller's own identity checks (user_id
    present, user_id belongs to the calling entity's org) are hard-reject conditions."""
    policy = db.scalar(select(RoutePolicy).where(RoutePolicy.subject_type == "user", RoutePolicy.subject_id == user_id, RoutePolicy.active == True))  # noqa: E712
    return policy.routes if policy else ["default-simulated-route"]
