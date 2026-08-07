"""Inbound delivery-report callbacks from upstream SMS providers. Tata calls back on the one
platform webhook URL Textzi registered with them (see provider_routes.py's
create_ttbs_provider_route) once a message reaches its final delivery state -- never a
customer-specific URL; Textzi is always the intermediary, and relays to the sending customer's
own webhook (ChannelSettings.dr_webhook_url) afterward, if they've configured one."""
import hmac
import json
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import ChannelSettings, DeliveryAttempt, DeliveryStatusCodeRule, Message, PlatformMessage, ProviderRoute
from .schemas import TtbsDrWebhookPayload
from .security import assert_safe_webhook_url, decrypt_secret
from .services import DomainError, credit_wallet, mask_mobile, redact_payload_values

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class _NoRedirect(HTTPRedirectHandler):
    """urlopen's default opener follows HTTP redirects transparently, which would completely
    defeat assert_safe_webhook_url's SSRF guard below it: a customer's webhook URL passes
    validation (it's a real public host they control), but that host can respond with a 302 to
    e.g. http://169.254.169.254/... (cloud metadata) or any private/internal address, and the
    redirect target is never re-validated. Raising here instead of following means a redirect is
    just treated as a failed relay attempt (caught below), never an SSRF vector."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirects are not followed for outbound webhook relays", headers, fp)


_no_redirect_opener = build_opener(_NoRedirect)


def _ttbs_reports_failure(payload: TtbsDrWebhookPayload) -> bool:
    """DeliveryStatusCodeRule alone means an unmapped code silently reads as a billable success --
    confirmed live as a real false positive: DeliveryStatusCode 93 came back with TTBS's own
    DeliveryStatus text reading "UNDELIVERABLE" (the SMS never reached a real handset), yet no
    admin rule existed for code 93, so it was recorded as "delivered". TTBS already tells us in
    plain text whether a code means success -- trust that as the primary signal instead of
    requiring an admin to have pre-registered every possible code TTBS might ever send."""
    return payload.DeliveryStatus is not None and payload.DeliveryStatus.strip().upper() != "DELIVERED"


def _resolve_ttbs_route_by_token(db: Session, token: str) -> ProviderRoute | None:
    for row in db.scalars(select(ProviderRoute).where(ProviderRoute.provider_type == "ttbs")).all():
        secret_encrypted = row.config.get("webhook_secret_encrypted")
        if secret_encrypted and hmac.compare_digest(decrypt_secret(secret_encrypted), token):
            return row
    return None


def _relay_to_customer(webhook_url: str, payload: dict) -> tuple[str, str | None]:
    """Best-effort forward to the customer's own DR webhook -- a slow or broken customer
    endpoint must never affect Textzi's own delivery-report processing, so failures here are
    swallowed rather than raised, not propagated. assert_safe_webhook_url is re-checked here, not
    just once when the customer saved the URL -- a hostname can resolve safely at save time and
    to a private/internal address at request time (DNS rebinding), so every actual outbound call
    re-validates against whatever the hostname resolves to right now. Returns (status, error) so
    the caller can persist what actually happened onto the DeliveryAttempt row, instead of this
    being invisible everywhere the way it was before."""
    try:
        assert_safe_webhook_url(webhook_url)
        request = Request(webhook_url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with _no_redirect_opener.open(request, timeout=5):
            pass
        return "success", None
    except (OSError, ValueError) as exc:
        return "failed", str(exc)[:300]


@router.post("/ttbs/dr")
def ttbs_delivery_report(payload: TtbsDrWebhookPayload, token: str, db: Session = Depends(get_db)):
    resolved_route = _resolve_ttbs_route_by_token(db, token)
    if not resolved_route:
        # Same response regardless of *why* the token doesn't match -- no signal for a probing
        # caller either way.
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    # Row-locked so concurrent DR callbacks for the same SubmissionID (a TTBS retry racing a
    # duplicate, or a replay) serialize instead of all reading status=="submitted" and all
    # crediting a refund independently -- without this, N concurrent requests produce N refunds
    # for one actual delivery event even though the "already processed" check below looks correct
    # in isolation. Also scoped to the route the token resolved to -- with more than one TTBS
    # route configured, each has its own distinct secret, and without this a caller holding one
    # route's secret could forge a DR for a SubmissionID that actually belongs to a different
    # route's traffic.
    attempt = db.scalar(select(DeliveryAttempt).where(DeliveryAttempt.provider_message_id == payload.SubmissionID, DeliveryAttempt.route == resolved_route.route_name).with_for_update())
    if not attempt:
        # Not a tenant message -- check the platform's own sends (login/verification OTPs, see
        # auth.py's _send_platform_otp_sms) before giving up. These never had a code path here at
        # all previously, confirmed live: every Platform Message stayed "submitted" forever
        # regardless of what TTBS actually reported, since this function only ever looked at
        # DeliveryAttempt.
        platform_message = db.scalar(
            select(PlatformMessage).where(PlatformMessage.provider_message_id == payload.SubmissionID, PlatformMessage.route == resolved_route.route_name).with_for_update(),
        )
        if not platform_message:
            # Ack (not 404) -- don't give a caller any signal about which submission ids are real,
            # and don't make TTBS retry forever for something we'll never be able to match.
            return {"status": "ignored", "reason": "unknown_submission_id"}
        if platform_message.status in {"delivered", "delivery_failed"}:
            return {"status": "already_processed"}
        rule = db.get(DeliveryStatusCodeRule, payload.DeliveryStatusCode)
        platform_message.delivery_status_code = payload.DeliveryStatusCode
        platform_message.delivered_at = datetime.now(timezone.utc)
        platform_message.webhook_payload = payload.model_dump()
        platform_message.status = "delivery_failed" if (rule or _ttbs_reports_failure(payload)) else "delivered"
        db.commit()
        return {"status": "processed"}

    if attempt.status in {"delivered", "delivery_failed"}:
        # Already processed (TTBS retry / duplicate callback) -- idempotent no-op. Most
        # importantly this guarantees a message is never refunded twice.
        return {"status": "already_processed"}

    rule = db.get(DeliveryStatusCodeRule, payload.DeliveryStatusCode)
    attempt.delivery_status_code = payload.DeliveryStatusCode
    attempt.delivered_at = datetime.now(timezone.utc)
    message = db.get(Message, attempt.message_id)
    webhook_payload = payload.model_dump()
    # TtbsDrWebhookPayload.Recipient is optional -- mask_mobile has no None-guard of its own, so
    # this must not attempt to redact/mask a value that was never actually present, or a DR
    # missing that field would 500 before ever being recorded.
    if message and message.is_encrypted and payload.Recipient:
        webhook_payload = redact_payload_values(webhook_payload, {payload.Recipient: mask_mobile(payload.Recipient)})
    attempt.webhook_payload = webhook_payload

    if rule or _ttbs_reports_failure(payload):
        # Failure if an admin explicitly flagged this code, OR TTBS's own DeliveryStatus text
        # says anything other than "DELIVERED" -- see _ttbs_reports_failure. Refunding still
        # requires an explicit admin rule (rule.refund) -- accuracy of the status label shouldn't
        # by itself move money; that stays an admin-gated decision.
        attempt.status = "delivery_failed"
        attempt.error = ((rule.label if rule and rule.label else None) or payload.DeliveryStatus or f"DeliveryStatusCode {payload.DeliveryStatusCode}")[:300]
        if message:
            message.status = "delivery_failed"
        if rule and rule.refund:
            # Refund exactly what was charged at send time (services.sms_segment_credits -- 1+
            # credits depending on message length), not a hardcoded 1, which would under-refund
            # any multi-segment message.
            try:
                credit_wallet(db, attempt.entity_id, message.credits_charged if message else 1, transaction_type="refund_delivery_failed", reference=attempt.message_id)
            except DomainError:
                pass
    else:
        # No rule for this code and TTBS's own status text says "DELIVERED" (or is absent) --
        # counts as a billable success (the charge from send time stands).
        attempt.status = "delivered"
        if message:
            message.status = "delivered"

    db.commit()

    channel_settings = db.get(ChannelSettings, (attempt.entity_id, "sms"))
    if channel_settings and channel_settings.dr_webhook_url:
        relay_payload = {
            "message_id": attempt.message_id,
            "recipient": payload.Recipient,
            "status": attempt.status,
            "delivery_status_code": payload.DeliveryStatusCode,
            "delivered_at": attempt.delivered_at.isoformat(),
        }
        status, error = _relay_to_customer(channel_settings.dr_webhook_url, relay_payload)
        attempt.customer_webhook_url = channel_settings.dr_webhook_url
        attempt.customer_webhook_payload = relay_payload
        attempt.customer_webhook_status = status
        attempt.customer_webhook_error = error
        attempt.customer_webhook_sent_at = datetime.now(timezone.utc)
    else:
        attempt.customer_webhook_status = "not_configured"
    db.commit()

    return {"status": "processed"}
