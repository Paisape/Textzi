"""Provider dispatch: attempts a message against its route plan, trying failover routes in
order and recording a DeliveryAttempt per try. Shared by the internal worker endpoint
(main.py, called via /v1/internal/messages/{id}/dispatch with the worker key) and the
dashboard compose endpoint (sms.py) -- there is no real queue consumer yet, so the dashboard
dispatches inline right after accepting a message instead of waiting on one."""
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import DeliveryAttempt, Header as HeaderModel, Message, PeId, ProviderRoute, Template
from .providers import HttpsSmsProvider, ProviderMessage, SimulatedSmsProvider, TtbsSmsProvider
from .security import decrypt_recipient_lenient, decrypt_secret
from .services import DomainError, credit_wallet, mask_mobile, redact_payload_values, ttbs_webhook_url as _ttbs_webhook_url


def _decrypt_route_secret(route: str, encrypted: str) -> str:
    # A route's stored secret can fail to decrypt (e.g. a rotated Fernet key, or a corrupted
    # value) -- re-raised as HTTPException so dispatch_message's per-route try/except treats it
    # exactly like a missing/incomplete config: this route's own failure, not a reason to abandon
    # the rest of the route plan. Fernet's InvalidToken previously escaped uncaught here, crashing
    # the whole dispatch instead of falling through to the next route.
    try:
        return decrypt_secret(encrypted)
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail=f"Provider route '{route}' has a secret that could not be decrypted") from exc


def provider_for_route(db: Session, route: str) -> HttpsSmsProvider | TtbsSmsProvider | SimulatedSmsProvider:
    provider_route = db.scalar(select(ProviderRoute).where(ProviderRoute.route_name == route))
    if provider_route and provider_route.provider_type == "https":
        cfg = provider_route.config
        endpoint = cfg.get("endpoint")
        if not endpoint:
            # Only reachable via direct DB tampering -- the admin API always writes a valid
            # config -- but fail with a clear message rather than an uncaught KeyError either way.
            raise HTTPException(status_code=500, detail=f"Provider route '{route}' has an incomplete https config (missing endpoint)")
        return HttpsSmsProvider(
            endpoint=endpoint,
            method=cfg.get("method", "POST"),
            auth_style=cfg.get("auth_style", "none"),
            auth_key_name=cfg.get("auth_key_name"),
            auth_value=_decrypt_route_secret(route, cfg["auth_value_encrypted"]) if cfg.get("auth_value_encrypted") else None,
            param_mapping=cfg.get("param_mapping", {}),
        )
    if provider_route and provider_route.provider_type == "ttbs":
        cfg = provider_route.config
        endpoint, user, pswd_encrypted = cfg.get("endpoint"), cfg.get("user"), cfg.get("pswd_encrypted")
        if not endpoint or not user or not pswd_encrypted:
            raise HTTPException(status_code=500, detail=f"Provider route '{route}' has an incomplete ttbs config (missing endpoint/user/pswd)")
        webhook_secret_encrypted = cfg.get("webhook_secret_encrypted")
        webhook_url = _ttbs_webhook_url(db, _decrypt_route_secret(route, webhook_secret_encrypted)) if webhook_secret_encrypted else None
        return TtbsSmsProvider(endpoint=endpoint, user=user, pswd=_decrypt_route_secret(route, pswd_encrypted), webhook_url=webhook_url)
    return SimulatedSmsProvider()


def dispatch_message(db: Session, message: Message) -> dict:
    if message.status not in {"accepted", "queued"}:
        return {"message_id": message.id, "status": message.status, "detail": "Already dispatched"}
    template = db.get(Template, message.template_id)
    header = db.get(HeaderModel, template.header_id) if template else None
    if not template or not header:
        raise HTTPException(status_code=422, detail="Message DLT mapping is incomplete")
    # This customer's own registered DLT identity (never the platform's) -- Header.pe_id is a
    # FK to the PeId row, not the TRAI-registered value itself, so it needs one more lookup.
    pe_id_row = db.get(PeId, header.pe_id)
    route_plan = message.route_plan or ([message.route] if message.route else ["default-simulated-route"])
    # The real SMS the recipient gets is never affected by the encryption toggle -- only
    # Textzi's own stored copy/visibility into it. Decrypt right before handing off to the
    # provider; Logs/Reports never see the plaintext. recipient is stored encrypted too (same
    # condition as the body) so it needs the same decrypt here -- the provider has to receive the
    # real number, not the ciphertext.
    body = decrypt_secret(message.rendered_body) if message.is_encrypted else message.rendered_body
    recipient = decrypt_recipient_lenient(message.recipient) if message.is_encrypted else message.recipient
    for route in route_plan:
        try:
            provider = provider_for_route(db, route)
            result = provider.send(ProviderMessage(
                message_id=message.id, recipient=recipient, sender=header.value, body=body,
                pe_id=pe_id_row.value if pe_id_row else None, template_id=template.dlt_template_id,
            ))
        except HTTPException as exc:
            # A route can be mis-configured (missing endpoint/creds) or its stored secret can fail
            # to decrypt (e.g. a rotated Fernet key) -- either is this route's own failure, not a
            # reason to abandon the rest of the route plan. Record it and try the next route, same
            # as a provider-reported failure below.
            attempt = DeliveryAttempt(
                message_id=message.id, entity_id=message.entity_id, route=route,
                status="failed", error=str(exc.detail),
            )
            db.add(attempt)
            continue
        # Whatever actually went to the provider is, by definition, the real plaintext -- the
        # recipient's handset has to receive readable text regardless of Textzi's own storage
        # encryption toggle. Scrub the same two plaintext values (by value, not by field name --
        # provider adapters name their fields differently) out of the telemetry we persist, so an
        # admin viewing this route-level record never sees more than they already couldn't via
        # the message's own is_encrypted masking.
        request_payload = result.request_payload
        if message.is_encrypted and request_payload:
            request_payload = redact_payload_values(request_payload, {body: "[Encrypted]", recipient: mask_mobile(recipient)})
        attempt = DeliveryAttempt(
            message_id=message.id, entity_id=message.entity_id, route=route, provider_message_id=result.provider_message_id,
            status="submitted" if result.accepted else "failed", error=result.error,
            request_payload=request_payload, response_body=result.response_body,
        )
        db.add(attempt)
        if result.accepted:
            message.route, message.status = route, "submitted"
            db.commit(); db.refresh(attempt)
            return {"message_id": message.id, "status": message.status, "route": route, "provider": provider.name, "provider_message_id": attempt.provider_message_id}
    message.status = "failed"
    # The credits_charged debit already happened at compose/accept time (services.sms_segment_credits
    # -- 1+ credits depending on message length), before delivery was ever attempted -- if every
    # route failed, nothing was actually delivered, so refund exactly what was charged rather than
    # a hardcoded 1, which would under-refund any multi-segment message.
    try:
        credit_wallet(db, message.entity_id, message.credits_charged, transaction_type="refund_failed_delivery", reference=message.id)
    except DomainError:
        pass
    db.commit()
    return {"message_id": message.id, "status": "failed", "detail": "All primary and failover routes failed"}
