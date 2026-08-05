"""Provider boundary: public Textzi APIs never depend on provider-specific payloads."""
import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _ttbs_recipient(mobile: str) -> str:
    """TTBS's own docs are explicit: "Mobile number given should include the national calling
    code. Example: 919823456789" -- no '+', just '91' directly prefixed. Textzi stores/collects
    mobile numbers as a bare 10-digit number throughout (every mobile input in this app, e.g.
    verify-account.vue's "9876543210" placeholder, collects it exactly this way), and nothing
    upstream of this provider ever added the prefix -- confirmed live, a real send to a real
    handset was accepted and even DR'd back as "delivered" by Tata's own system, yet the SMS
    never arrived, root-caused to this exact gap via Tata's HTTP Push API documentation. Only
    normalizes a bare 10-digit Indian mobile number (leaves anything else -- already-prefixed,
    a different length/format -- untouched, so this can't mangle a number it doesn't recognize)."""
    digits = mobile.strip()
    if len(digits) == 10 and digits[0] in "6789":
        return "91" + digits
    return digits


# TTBS's own "HTTP PUSH API" documentation (Table 2-4-2, DR for DLT Error Codes, plus the
# adjoining SMSC/module-error table) -- codes not listed here (e.g. TTBS's own success code, or
# anything TTBS adds later) have no built-in description; DeliveryStatusCodeRule.label remains
# the way an admin can label/refund an unlisted code. This dict is purely for showing a
# human-readable reason in the admin report -- it never affects delivered/failed status or
# billing (see _ttbs_reports_failure in webhooks.py for that).
TTBS_DELIVERY_STATUS_DESCRIPTIONS: dict[int, str] = {
    74: "Category has been Blocked",
    75: "Mode is blocked",
    76: "Mandatory fields are missing",
    79: "Entity is blacklisted",
    80: "Entity is not active",
    81: "RTM is blacklisted",
    82: "RTM is not active",
    83: "Header is not active",
    84: "Header is blacklisted",
    85: "Header is not owned by Entity",
    86: "Template ID not registered in DLT system",
    87: "Content template is not owned by Entity",
    88: "Input file format is not valid",
    89: "RTM is unauthorized",
    90: "Template ID status in DLT is in Inactive or Blocked state",
    91: "Invalid MSISDN number",
    92: "Template dynamic variable exceeded max length",
    93: "Invalid API Key",
    94: "Invalid Template ID - NULL or Alpha or Length not valid",
    95: "Header is not mapped with template",
    96: "Consent Template is not mapped with template",
    97: "SMS content is not mapped with template",
    98: "No Available Time to Deliver",
    99: "Days are Blocked",
    100: "HTTP Client errors (4xx)",
    101: "HTTP Server Errors (5xx)",
    600: "Native Error from SMSC",
    601: "Internal Module Timeout",
    602: "Submit Failed - EXPIRED",
    603: "Message Expired",
    604: "Message Timedout",
    605: "UDH missing fragment",
    702: "Submit Failed - SUBMIT_FAILED",
    703: "Message Expired",
    704: "Message Expired",
    705: "UDH missing fragment",
}


def ttbs_delivery_status_description(code: int | None) -> str | None:
    return TTBS_DELIVERY_STATUS_DESCRIPTIONS.get(code) if code is not None else None


def _extract_ttbs_message_id(body: str) -> str | None:
    """TTBS's campaignService/campaigns/qs endpoint was originally a plain short ID in the
    response body -- confirmed live it now returns a JSON object instead (e.g. {"campaignId":
    "...", "jobId": "...", "requireApproval": false}), and storing the raw (truncated-at-120-char)
    response text as provider_message_id meant it could never match the SubmissionID a later
    delivery-report webhook call references, since it was a cut-off JSON fragment, not an ID.
    Falls back to the original raw-body behavior if the response isn't JSON, for any TTBS
    integration that genuinely still returns a plain string."""
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return body[:120] or None
    if not isinstance(parsed, dict):
        return body[:120] or None
    for key in ("jobId", "campaignId", "SubmissionID", "submissionId", "id"):
        value = parsed.get(key)
        if value:
            return str(value)[:120]
    return body[:120] or None


@dataclass(frozen=True)
class ProviderMessage:
    message_id: str
    recipient: str
    sender: str
    body: str
    # DLT identity for this specific send -- platform messages carry the platform's own
    # PE_ID/template (PlatformSmsSettings), tenant messages carry the sending customer's own
    # registered PE_ID/template (Header/Template). Never mixed: which one lands here is decided
    # entirely by the caller (dispatch.py vs auth.py's _send_platform_otp_sms), not by the
    # provider itself.
    pe_id: str | None = None
    template_id: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    accepted: bool
    provider_message_id: str | None = None
    error: str | None = None
    # Full telemetry for admin debugging -- request_payload is whatever was actually put on the
    # wire with any credential (password, auth token) replaced by a "[REDACTED]" marker before
    # it ever reaches this dataclass, never the raw value; response_body is the provider's raw
    # response text, uncapped by the truncation `error` applies for its own display purposes.
    request_payload: dict | None = None
    response_body: str | None = None


class SmsProvider(Protocol):
    name: str

    def send(self, message: ProviderMessage) -> ProviderResult: ...

    def health_check(self) -> bool: ...


class SimulatedSmsProvider:
    """Local-only adapter; keeps development safe from accidental SMS sends."""
    name = "simulated"

    def send(self, message: ProviderMessage) -> ProviderResult:
        payload = {"recipient": message.recipient, "sender": message.sender, "body": message.body}
        return ProviderResult(accepted=True, provider_message_id=f"sim-{message.message_id}", request_payload=payload, response_body="simulated-ok")

    def health_check(self) -> bool:
        return True


class HttpsSmsProvider:
    """Generic HTTPS SMS provider adapter. Every provider's REST API names its fields and
    authenticates differently, so the request shape is data (endpoint/method/auth/param_mapping),
    not code — one class serves any HTTPS-based provider without a new implementation per vendor."""
    name = "https"

    def __init__(self, endpoint: str, method: str = "POST", auth_style: str = "none", auth_key_name: str | None = None, auth_value: str | None = None, param_mapping: dict[str, str] | None = None, timeout_seconds: int = 10):
        self.endpoint = endpoint
        self.method = method.upper()
        self.auth_style = auth_style
        self.auth_key_name = auth_key_name
        self.auth_value = auth_value
        self.param_mapping = param_mapping or {}
        self.timeout_seconds = timeout_seconds

    def _mapped_params(self, message: ProviderMessage) -> dict[str, str]:
        logical = {"to": message.recipient, "from": message.sender, "content": message.body}
        return {self.param_mapping.get(key, key): value for key, value in logical.items()}

    def send(self, message: ProviderMessage) -> ProviderResult:
        params = self._mapped_params(message)
        headers: dict[str, str] = {}
        query: dict[str, str] = {}
        if self.auth_style == "header" and self.auth_key_name and self.auth_value:
            headers[self.auth_key_name] = self.auth_value
        elif self.auth_style == "bearer" and self.auth_value:
            headers["Authorization"] = f"Bearer {self.auth_value}"
        elif self.auth_style == "query" and self.auth_key_name and self.auth_value:
            query[self.auth_key_name] = self.auth_value

        redacted_query = {k: ("[REDACTED]" if k == self.auth_key_name else v) for k, v in query.items()}
        redacted_headers = {k: ("[REDACTED]" if k.lower() == "authorization" or k == self.auth_key_name else v) for k, v in headers.items()}
        request_payload = {"method": self.method, "endpoint": self.endpoint, "params": params, "query": redacted_query, "headers": redacted_headers}

        try:
            if self.method == "GET":
                request = Request(f"{self.endpoint}?{urlencode({**query, **params})}", headers=headers, method="GET")
            else:
                url = f"{self.endpoint}?{urlencode(query)}" if query else self.endpoint
                request = Request(url, data=urlencode(params).encode(), headers={**headers, "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode(errors="replace").strip()
                accepted = 200 <= response.status < 300
                return ProviderResult(accepted=accepted, provider_message_id=(body[:120] or None) if accepted else None, error=None if accepted else body[:200], request_payload=request_payload, response_body=body[:2000])
        except OSError as exc:
            return ProviderResult(accepted=False, error=str(exc), request_payload=request_payload)

    def health_check(self) -> bool:
        try:
            with urlopen(self.endpoint, timeout=self.timeout_seconds) as response:
                return 200 <= response.status < 500
        except OSError:
            return False


class TtbsSmsProvider:
    """Tata Tele Business Services SMSGW -- the HTTP Query String interface
    (campaignService/campaigns/qs). `user`/`pswd` are Textzi's own platform-wide TTBS account
    (our agreement is with Tata; the customer's agreement is with Textzi) -- one fixed
    credential pair used for every send regardless of whose message it is. `pe_id`/`template_id`
    go the other way: they vary per message (platform's own DLT identity for platform SMS,
    the sending customer's registered DLT identity for tenant SMS) and are threaded in per-send
    via ProviderMessage, never baked into this class's own config."""
    name = "ttbs"
    # TTBS's own doc: "Maximum URL length is 2000 chars." A long template body plus
    # recipient/sender/user/pswd/PE_ID/Template_ID -- and URL-encoding expansion for Unicode or
    # special characters in the body -- can realistically get there. Checked before sending so
    # an over-length message fails clearly and immediately, instead of an opaque TTBS-side
    # rejection (or worse, silent truncation by some proxy in between).
    MAX_URL_LENGTH = 2000

    def __init__(self, endpoint: str, user: str, pswd: str, webhook_url: str | None = None, timeout_seconds: int = 10):
        self.endpoint = endpoint
        self.user = user
        self.pswd = pswd
        # Textzi's own platform DR callback URL (already carries its own auth token in the query
        # string) -- set once per route from platform config, never per-message. When unset, `dr`
        # stays disabled: same fail-open behavior as before this feature existed, not a hard
        # dependency for sending to work.
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds

    def _params(self, message: ProviderMessage) -> dict[str, str]:
        params = {
            "user": self.user,
            "pswd": self.pswd,
            "recipient": _ttbs_recipient(message.recipient),
            "sender": message.sender,
            "msg": message.body,
            "channel": "2.1",
            "dr": "1" if self.webhook_url else "0",
        }
        if self.webhook_url:
            params["drUri"] = self.webhook_url
        if message.pe_id:
            params["PE_ID"] = message.pe_id
        if message.template_id:
            params["Template_ID"] = message.template_id
        return params

    def send(self, message: ProviderMessage) -> ProviderResult:
        params = self._params(message)
        # Redact the account password before this ever leaves the provider boundary -- callers
        # persist request_payload verbatim for admin telemetry, and the real TTBS password has no
        # legitimate reason to ever appear in that view (drUri's own auth token is left as-is:
        # it's already re-fetchable by an admin via the dedicated webhook-url endpoint, so
        # showing it again here isn't a new exposure).
        redacted_params = {**params, "pswd": "[REDACTED]"}
        url = f"{self.endpoint}?{urlencode(params)}"
        if len(url) > self.MAX_URL_LENGTH:
            return ProviderResult(accepted=False, error=f"Message too long for the TTBS QS interface: request would be {len(url)} chars (limit {self.MAX_URL_LENGTH}). Shorten the message or switch this route to the TTBS REST API.", request_payload=redacted_params)
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode(errors="replace").strip()
                accepted = 200 <= response.status < 300
                return ProviderResult(accepted=accepted, provider_message_id=_extract_ttbs_message_id(body) if accepted else None, error=None if accepted else body[:200], request_payload=redacted_params, response_body=body[:2000])
        except HTTPError as exc:
            # TTBS reports real failures (401 unauthorized, 402 insufficient balance, 400
            # missing fields, ...) as non-2xx HTTP responses, which urlopen raises rather than
            # returns -- surface the actual status + body (this is TTBS's real error-reporting
            # channel), never the request itself, since the request URL carries user/pswd.
            try:
                body = exc.read().decode(errors="replace").strip()
            except OSError:
                body = ""
            return ProviderResult(accepted=False, error=f"HTTP {exc.code}: {body[:150]}" if body else f"HTTP {exc.code}", request_payload=redacted_params, response_body=f"HTTP {exc.code}: {body[:2000]}" if body else f"HTTP {exc.code}")
        except URLError as exc:
            # Connection-level failure (DNS, timeout, refused, ...) -- exc.reason is a plain
            # socket-level message/exception, never the request URL, so it's safe to include.
            return ProviderResult(accepted=False, error=f"{exc.__class__.__name__}: {exc.reason}", request_payload=redacted_params)

    def health_check(self) -> bool:
        try:
            with urlopen(self.endpoint, timeout=self.timeout_seconds) as response:
                return 200 <= response.status < 500
        except HTTPError as exc:
            return exc.code < 500
        except URLError:
            return False
