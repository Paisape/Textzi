import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .admin import router as admin_router, require_admin
from .archive_jobs import run as run_archive_job
from .auth import router as auth_router
from .catalog_sync import router as catalog_sync_router, sync_all_catalogs
from .channel_billing import router as channel_billing_router
from .channels import router as channels_router
from .crm import router as crm_router, send_due_scheduled_reports
from .crm_documents import router as crm_documents_router
from .crm_email import poll_all_email_inboxes, router as crm_email_router
from .crm_quotes import router as crm_quotes_router
from .crm_public import router as crm_public_router
from .crm_sequences import router as crm_sequences_router, run_due_steps as run_due_sequence_steps
from .database import Base, engine, get_db
from .dispatch import dispatch_message as run_dispatch
from .invoices import router as invoices_router
from .models import ApiLog, Entity, Message, Organization, RoutePolicy, User
from .onboarding import router as onboarding_router
from .payments import router as payments_router
from .payments_smart_collect import router as payments_smart_collect_router, run_smart_collect_reconciliation, webhook_router as smart_collect_webhook_router
from .platform_admin import router as platform_admin_router
from .provider_routes import router as provider_routes_router
from .public import router as public_router
from .reports import router as reports_router
from .sms import router as sms_router
from .team import router as team_router
from .testimonials import router as testimonials_router
from .two_factor import router as two_factor_router
from .waba import router as waba_router
from .waba_campaigns import router as waba_campaigns_router, run_due_campaigns
from .waba_inbox import router as waba_inbox_router
from .waba_orders import router as waba_orders_router
from .waba_realtime import router as waba_realtime_router
from .waba_reports import router as waba_reports_router
from .waba_webhooks import router as waba_webhooks_router
from .wallet import router as wallet_router
from .webchat import router as webchat_router
from .webchat_public import router as webchat_public_router
from .webchat_realtime import router as webchat_realtime_router
from .webhooks import router as webhooks_router
from .schemas import ApiSmsSendRequest, ApiSmsSendResponse, BulkSmsRecipientResult, BulkSmsSendRequest, BulkSmsSendResponse, RoutePolicyRequest, SmsSendResponse
from .security import encrypt_secret
from .services import (
    AuthenticationError, AuthorizationError, DomainError, RateLimitError, assert_not_opted_out, available_balance, client_ip,
    debit_wallet, enforce_rate_limit, is_encryption_enabled, mask_mobile, require_channel_active, resolve_entity_from_key,
    resolve_template_by_dlt_id, resolve_user_route_policy, sms_segment_credits,
)


# Attached directly to the "textzi" parent logger (every module-level logger in this app is
# named "textzi.<module>" and propagates up to it) rather than relying on root/basicConfig, since
# uvicorn's own CLI configures the root logger's handlers before this module is even imported --
# attaching here guarantees textzi.* messages reach stdout regardless of that ordering.
_textzi_logger = logging.getLogger("textzi")
_textzi_logger.setLevel(logging.INFO)
if not _textzi_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _textzi_logger.addHandler(_handler)

logger = logging.getLogger("textzi.archiving")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)  # Deployment uses Alembic migrations.

    # Runs the daily local/R2 archive job in-process rather than depending on a separate,
    # easy-to-forget Coolify scheduled-task step. BackgroundScheduler runs jobs on its own thread,
    # not the asyncio loop, so run_archive_job's synchronous DB/boto3 calls don't block requests.
    # Safe for this deployment's single, non-scaled api replica; even if that changes,
    # archive_jobs.run()'s own pg_try_advisory_lock already prevents a second concurrent run from
    # double-processing.
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_archive_job, CronTrigger(hour=2, minute=0), id="daily_archive_job", misfire_grace_time=3600)
    # CRM sales-sequence steps (Addendum 4 Phase 4) -- same in-process scheduler, no separate
    # infra. Hourly is granular enough for day-offset-based steps and cheap enough to just poll.
    scheduler.add_job(run_due_sequence_steps, IntervalTrigger(hours=1), id="crm_sequence_runner", misfire_grace_time=3600)
    # Email channel (Addendum 9) -- polls every connected EmailAccount's IMAP inbox for unseen
    # messages. 10 minutes is granular enough for a support inbox and cheap enough to just poll,
    # same reasoning as the hourly CRM sequence runner above.
    scheduler.add_job(poll_all_email_inboxes, IntervalTrigger(minutes=10), id="email_poll_job", misfire_grace_time=600)
    # Custom Report Builder's "email me this weekly/monthly" schedules -- one daily check (same
    # shape as the archive job above), not a per-report cron; the function itself decides what's
    # actually due today.
    scheduler.add_job(send_due_scheduled_reports, CronTrigger(hour=6, minute=0), id="scheduled_report_runner", misfire_grace_time=3600)
    # WhatsApp campaign scheduling -- picks up any campaign whose scheduled_at has passed. 5
    # minutes is granular enough that a customer scheduling "9am" actually goes out close to 9am,
    # unlike the hour/day-granularity jobs above.
    scheduler.add_job(run_due_campaigns, IntervalTrigger(minutes=5), id="waba_campaign_runner", misfire_grace_time=600)
    # Smart Collect's webhook is the primary/real-time credit path -- this is the fallback for a
    # payment that succeeded on Razorpay's side but whose webhook delivery never reached us
    # (network blip, a briefly-misconfigured secret, downtime). 15 minutes balances catching a
    # missed credit reasonably quickly against not hammering Razorpay's API per active account.
    scheduler.add_job(run_smart_collect_reconciliation, IntervalTrigger(minutes=15), id="smart_collect_reconcile_job", misfire_grace_time=900)
    # WhatsApp Commerce catalog sync (Addendum 14 Phase 1) -- keeps the local WabaCatalogItem
    # mirror close to Meta's own catalog for the agent-inbox product picker. Hourly, same
    # reasoning as the CRM sequence runner: granular enough, cheap enough to just poll.
    scheduler.add_job(sync_all_catalogs, IntervalTrigger(hours=1), id="catalog_sync_job", misfire_grace_time=3600)
    scheduler.start()
    logger.info("scheduled daily archive job (02:00 UTC), hourly CRM sequence runner, 10-minute email poll, daily report-schedule check, 5-minute campaign runner, 15-minute Smart Collect reconcile, and hourly catalog sync")

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(title="Textzi API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(catalog_sync_router)
app.include_router(channel_billing_router)
app.include_router(channels_router)
app.include_router(crm_router)
app.include_router(crm_documents_router)
app.include_router(crm_email_router)
app.include_router(crm_public_router)
app.include_router(crm_quotes_router)
app.include_router(crm_sequences_router)
app.include_router(invoices_router)
app.include_router(onboarding_router)
app.include_router(payments_router)
app.include_router(payments_smart_collect_router)
app.include_router(smart_collect_webhook_router)
app.include_router(platform_admin_router)
app.include_router(provider_routes_router)
app.include_router(public_router)
app.include_router(reports_router)
app.include_router(sms_router)
app.include_router(team_router)
app.include_router(testimonials_router)
app.include_router(two_factor_router)
app.include_router(waba_router)
app.include_router(waba_campaigns_router)
app.include_router(waba_inbox_router)
app.include_router(waba_orders_router)
app.include_router(waba_realtime_router)
app.include_router(waba_reports_router)
app.include_router(waba_webhooks_router)
app.include_router(wallet_router)
app.include_router(webchat_router)
app.include_router(webchat_public_router)
app.include_router(webchat_realtime_router)
app.include_router(webhooks_router)


@app.get("/health/live", tags=["health"])
def live(): return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready", "dependencies": {"database": "ok"}}


def require_worker(x_worker_key: str = Header(...)):
    if settings.environment != "development" and settings.worker_key.startswith("development-"):
        raise HTTPException(status_code=503, detail="Worker key is not configured")
    if not hmac.compare_digest(x_worker_key, settings.worker_key):
        raise HTTPException(status_code=401, detail="Invalid worker key")


def _same_org_user_id(db: Session, entity: Entity, x_user_id: str | None) -> str | None:
    """RoutePolicy has no entity/organization ownership column at all (see models.py) -- it's a
    flat subject_type/subject_id table, originally meant for the authenticated dashboard's own
    resolve_routes(db, user.id, ...) call (sms.py's compose_sms), where user.id comes from a
    verified JWT. This external, X-Api-Key-authenticated endpoint has no per-user identity of its
    own, so a caller-supplied X-User-Id header is otherwise just an unverified string -- passing
    it straight into resolve_routes would let any entity select ANY organization's per-user route
    policy by guessing/knowing another org's user id.

    Rejects outright (403) rather than silently falling back to the default route when a
    caller-supplied user_id doesn't resolve to a real user in the calling entity's own
    organization -- a mismatch here almost always means a misconfigured integration (stale/typo'd
    id, or an id copied from the wrong account), and silently degrading to the default route hid
    that misconfiguration behind what looked like a normal successful send. There's no equivalent
    check possible for X-User-Group (no Group model/ownership concept exists anywhere in the
    schema), so that header is still accepted for logging only and never reaches resolve_routes."""
    if not x_user_id:
        return None
    candidate = db.get(User, x_user_id)
    if not candidate or candidate.organization_id != entity.organization_id:
        raise AuthorizationError("user_id does not belong to this account")
    return x_user_id


@app.post("/v1/sms/send", response_model=ApiSmsSendResponse, tags=["sms"])
def send_sms(payload: ApiSmsSendRequest, request: Request, x_api_key: str = Header(min_length=20), idempotency_key: str | None = Header(default=None, max_length=120), x_user_id: str | None = Header(default=None), x_user_group: str | None = Header(default=None), db: Session = Depends(get_db)):
    started, request_id, entity_id = time.perf_counter(), str(uuid.uuid4()), None
    # Whatever the try block sets these to by the time it exits (success or any except clause
    # below) is what actually gets logged -- previously this was hardcoded to 202 in the finally
    # block regardless of outcome, so a failed call (401/403/422/409) was indistinguishable from
    # a successful one in api_logs.
    status_code, error_detail, message_id = 202, None, None
    caller_ip = client_ip(request)
    try:
        entity = resolve_entity_from_key(db, x_api_key, caller_ip); entity_id = entity.id
        if not x_user_id:
            status_code, error_detail = 422, "user_id is required"
            raise HTTPException(status_code=422, detail="user_id is required -- pass it as the X-User-Id header (POST) or user_id query param (GET), the recipient's real internal User.id from the Team page.")
        verified_user_id = _same_org_user_id(db, entity, x_user_id)
        enforce_rate_limit(f"ratelimit:sms:{entity.id}", settings.sms_rate_limit_max_requests, settings.sms_rate_limit_window_seconds)
        require_channel_active(db, entity.id, "sms")
        if idempotency_key:
            # Rejects outright rather than silently returning the original result -- each
            # Idempotency-Key must be used exactly once. No Message row is created and no wallet
            # debit happens on this path (both only occur further down), so a rejected reuse is
            # never charged.
            existing = db.scalar(select(Message).where(Message.entity_id == entity.id, Message.idempotency_key == idempotency_key))
            if existing:
                status_code, error_detail = 409, "Idempotency-Key already used"
                raise HTTPException(status_code=409, detail="This Idempotency-Key has already been used -- each key may only be used once. Send a new, unique key for a new message, or omit it entirely if you don't need replay protection.")
        assert_not_opted_out(db, entity.id, payload.mobile)
        # No render_template call here -- the caller sends the complete, already-composed
        # message (payload.message) exactly as it should go out. resolve_template_by_dlt_id
        # still verifies it's one of this entity's own approved templates and resolves the
        # header/PE_ID/route mapping registered for it.
        template = resolve_template_by_dlt_id(db, entity.id, payload.template_id)
        route_plan = resolve_user_route_policy(db, verified_user_id)
        route = route_plan[0]
        rendered_body = payload.message
        encrypted = is_encryption_enabled(db, entity.id, "sms")
        credits = sms_segment_credits(rendered_body)
        message = Message(
            entity_id=entity.id, template_id=template.id, recipient=encrypt_secret(payload.mobile) if encrypted else payload.mobile,
            rendered_body=encrypt_secret(rendered_body) if encrypted else rendered_body,
            is_encrypted=encrypted, route=route, route_plan=route_plan, idempotency_key=idempotency_key,
            credits_charged=credits,
            request_payload={
                "mobile": mask_mobile(payload.mobile) if encrypted else payload.mobile,
                "template_id": payload.template_id,
                "message": None if encrypted else payload.message,
                "idempotency_key": idempotency_key,
                "x_user_id": x_user_id,
                "x_user_group": x_user_group,
            },
        )
        db.add(message); db.flush()
        message_id = message.id
        debit_wallet(db, entity.id, credits, reference=message.id)  # 1 credit per 160-char segment (services.sms_segment_credits)
        db.commit(); db.refresh(message)
        # No real queue consumer exists yet (see sms.py's compose_sms, which has always dispatched
        # the same way) -- without this call, a message accepted here just sits at status
        # "accepted" forever, since nothing else in the system ever reaches
        # /v1/internal/messages/{id}/dispatch on its own. Inline dispatch blocks this response on
        # the provider's own network latency (bounded by each provider adapter's own timeout,
        # currently 10s) -- acceptable for now given nothing else drives delivery, but a real
        # async worker consuming the already-provisioned RabbitMQ/Redis is the right fix before
        # this needs to handle meaningful throughput.
        run_dispatch(db, message)
        db.refresh(message)
        response = SmsSendResponse(status=message.status, message_id=message.id, route=message.route or route, balance=available_balance(db, entity.id), credits_charged=credits)
        message.response_payload = response.model_dump()
        db.commit()
        return response
    except AuthenticationError as exc:
        status_code, error_detail = 401, str(exc)
        db.rollback(); raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AuthorizationError as exc:
        status_code, error_detail = 403, str(exc)
        db.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        status_code, error_detail = 429, str(exc)
        db.rollback(); raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DomainError as exc:
        status_code, error_detail = 422, str(exc)
        db.rollback(); message_id = None; raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Same outcome as the explicit check above, for the rare race where two requests with the
        # same not-yet-used key both pass that check before either commits -- the database's own
        # unique constraint is what actually catches this one.
        status_code, error_detail = 409, "Idempotency-Key already used"
        db.rollback(); message_id = None; raise HTTPException(status_code=409, detail="This Idempotency-Key has already been used -- each key may only be used once.") from exc
    finally:
        metadata = {"method": request.method}
        if error_detail:
            metadata["error"] = error_detail
        db.add(ApiLog(
            request_id=request_id, entity_id=entity_id, message_id=message_id, endpoint=request.url.path, status_code=status_code,
            latency_ms=int((time.perf_counter()-started)*1000), metadata_json=metadata,
            # Both are attacker-influenceable (X-Forwarded-For when trust_proxy_headers is on;
            # CF-IPCountry is just a client header) -- truncated to the column widths the same way
            # user_agent already was, so an oversized value degrades to a truncated log entry
            # instead of a Postgres DataError replacing the real response with an unhandled 500.
            ip_address=(caller_ip or "")[:64], country=(request.headers.get("CF-IPCountry") or "")[:4] or None,
            user_agent=request.headers.get("user-agent", "")[:300],
        ))
        db.commit()


@app.get("/v1/sms/send-url", response_model=ApiSmsSendResponse, tags=["sms"])
def send_sms_via_url(
    request: Request,
    api_key: str = Query(min_length=20),
    mobile: str = Query(...),
    template_id: str = Query(...),
    message: str = Query(...),
    idempotency_key: str | None = Query(default=None, max_length=120),
    user_id: str | None = Query(default=None),
    user_group: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Query-string twin of POST /v1/sms/send, for integrations that can only fire a plain HTTP
    GET -- e.g. a system migrating off a raw carrier gateway URL like TTBS's own
    `.../campaigns/qs?recipient=...&msg=...&user=...&pswd=...`, which has no concept of a JSON
    body or custom headers. Delegates to send_sms itself (same auth, rate limit, opt-out check,
    template resolution, wallet debit, dispatch, ApiLog entry) rather than duplicating that logic.

    user_id (query param here, X-User-Id header on POST /v1/sms/send) is mandatory -- omitting it
    rejects the request with a 422 (this is an identity requirement, not just a routing hint), and
    it must resolve to a real User belonging to the same organization as the api_key's own entity
    or the request is rejected with a 403 (see _same_org_user_id). Must be the recipient's real
    internal User.id (found on the Team page), not their email.

    Once accepted, routing is decided by that user_id specifically via
    services.resolve_user_route_policy -- entity-level Route Policies are never consulted here at
    all (unlike the dashboard's own Compose feature, sms.py's compose_sms, which still falls
    through user -> group -> entity -> simulated via the separate resolve_routes). If the admin
    simply hasn't set up a Route Policy for this particular user, the send still succeeds -- it
    falls back straight to the simulated route, skipping the entity tier entirely, rather than
    being rejected.

    Putting api_key in the URL is inherently less safe than a header: it can end up logged along
    the way. Textzi's own side is covered -- ApiLog only ever stores request.url.path, never the
    query string (see the finally block in send_sms above), and uvicorn's access log is disabled
    in production (Dockerfile) so the key never hits container/Coolify logs either. Cloudflare's
    own edge request logs are outside Textzi's control, though, and will still show the full URL
    including this key -- scrubbing those is a Cloudflare-dashboard setting, not something this
    endpoint can affect."""
    try:
        payload = ApiSmsSendRequest(template_id=template_id, mobile=mobile, message=message)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return send_sms(payload, request, x_api_key=api_key, idempotency_key=idempotency_key, x_user_id=user_id, x_user_group=user_group, db=db)


@app.post("/v1/sms/send-bulk", response_model=BulkSmsSendResponse, tags=["sms"])
def send_sms_bulk(payload: BulkSmsSendRequest, request: Request, x_api_key: str = Header(min_length=20), x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    """One template, many recipients (capped at 100 -- see BulkSmsSendRequest -- since each is
    dispatched inline/synchronously, same as a single send; no real async worker exists yet, see
    send_sms's own note). Auth/channel-active/rate-limit/template resolution happen once for the
    whole call; each recipient is then processed independently so one bad number or an
    opted-out/insufficient-balance recipient partway through the batch doesn't roll back the
    ones that already succeeded -- the response reports a per-recipient result."""
    started, request_id, entity_id = time.perf_counter(), str(uuid.uuid4()), None
    status_code, error_detail = 202, None
    caller_ip = client_ip(request)
    try:
        entity = resolve_entity_from_key(db, x_api_key, caller_ip); entity_id = entity.id
        if not x_user_id:
            status_code, error_detail = 422, "user_id is required"
            raise HTTPException(status_code=422, detail="user_id is required -- pass it as the X-User-Id header, the recipient's real internal User.id from the Team page.")
        verified_user_id = _same_org_user_id(db, entity, x_user_id)
        # Costs len(recipients) units, not 1 -- otherwise a 100-recipient batch would only cost
        # as much rate-limit budget as a single send, letting bulk push up to
        # max_requests * 100 actual messages through the same window a single-send caller is
        # limited to max_requests for.
        enforce_rate_limit(f"ratelimit:sms:{entity.id}", settings.sms_rate_limit_max_requests, settings.sms_rate_limit_window_seconds, amount=len(payload.recipients))
        require_channel_active(db, entity.id, "sms")
        template = resolve_template_by_dlt_id(db, entity.id, payload.template_id)
        route_plan = resolve_user_route_policy(db, verified_user_id)
        route = route_plan[0]
        encrypted = is_encryption_enabled(db, entity.id, "sms")
    except AuthenticationError as exc:
        status_code, error_detail = 401, str(exc)
        db.rollback(); raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AuthorizationError as exc:
        status_code, error_detail = 403, str(exc)
        db.rollback(); raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        status_code, error_detail = 429, str(exc)
        db.rollback(); raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DomainError as exc:
        status_code, error_detail = 422, str(exc)
        db.rollback(); raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        metadata = {"method": request.method, "endpoint": "bulk"}
        if error_detail:
            metadata["error"] = error_detail
        db.add(ApiLog(
            request_id=request_id, entity_id=entity_id, endpoint=request.url.path, status_code=status_code,
            latency_ms=int((time.perf_counter()-started)*1000), metadata_json=metadata,
            ip_address=(caller_ip or "")[:64], country=(request.headers.get("CF-IPCountry") or "")[:4] or None,
            user_agent=request.headers.get("user-agent", "")[:300],
        ))
        db.commit()

    results: list[BulkSmsRecipientResult] = []
    for recipient in payload.recipients:
        try:
            assert_not_opted_out(db, entity.id, recipient.mobile)
            rendered_body = recipient.message
            credits = sms_segment_credits(rendered_body)
            message = Message(
                entity_id=entity.id, template_id=template.id, recipient=encrypt_secret(recipient.mobile) if encrypted else recipient.mobile,
                rendered_body=encrypt_secret(rendered_body) if encrypted else rendered_body,
                is_encrypted=encrypted, route=route, route_plan=route_plan, credits_charged=credits,
                request_payload={
                    "mobile": mask_mobile(recipient.mobile) if encrypted else recipient.mobile,
                    "template_id": payload.template_id,
                    "message": None if encrypted else recipient.message,
                    "bulk": True,
                },
            )
            db.add(message); db.flush()
            debit_wallet(db, entity.id, credits, reference=message.id)
            db.commit(); db.refresh(message)
        except DomainError as exc:
            db.rollback()
            results.append(BulkSmsRecipientResult(mobile=recipient.mobile, status="rejected", message_id=None, credits_charged=0, error=str(exc)))
            continue
        run_dispatch(db, message)
        db.refresh(message)
        message.response_payload = {"status": message.status, "message_id": message.id, "route": message.route or route, "credits_charged": credits}
        db.commit()
        results.append(BulkSmsRecipientResult(mobile=recipient.mobile, status=message.status, message_id=message.id, credits_charged=credits, error=None))

    rejected = sum(1 for r in results if r.status == "rejected")
    return BulkSmsSendResponse(accepted=len(results) - rejected, rejected=rejected, balance=available_balance(db, entity.id), results=results)


@app.post("/v1/internal/messages/{message_id}/dispatch", tags=["internal"], dependencies=[Depends(require_worker)])
def dispatch_message(message_id: str, db: Session = Depends(get_db)):
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return run_dispatch(db, message)


@app.get("/v1/admin/route-policies", tags=["routing"], dependencies=[Depends(require_admin)])
def list_route_policies(db: Session = Depends(get_db)):
    """subject_id for a "user"/"entity" policy is the real internal User.id/Entity.id (a UUID)
    -- meaningless on its own in the admin UI, so this batch-resolves a human label for every
    such policy in one query per type, rather than the frontend needing its own N+1 lookup or a
    separate unbounded fetch just to make the table readable."""
    policies = db.scalars(select(RoutePolicy).where(RoutePolicy.active == True)).all()  # noqa: E712
    user_ids = {p.subject_id for p in policies if p.subject_type == "user"}
    entity_ids = {p.subject_id for p in policies if p.subject_type == "entity"}
    labels: dict[str, str] = {}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            labels[u.id] = f"{u.full_name} ({u.email})"
    if entity_ids:
        entities = {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(entity_ids))).all()}
        org_ids = {e.organization_id for e in entities.values()}
        orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all()} if org_ids else {}
        for entity_id, entity in entities.items():
            org = orgs.get(entity.organization_id)
            labels[entity_id] = f"{org.name} — {entity.name}" if org else entity.name
    return [
        {"id": p.id, "subject_type": p.subject_type, "subject_id": p.subject_id, "subject_label": labels.get(p.subject_id), "routes": p.routes}
        for p in policies
    ]


@app.post("/v1/admin/route-policies", tags=["routing"], dependencies=[Depends(require_admin)])
def upsert_route_policy(payload: RoutePolicyRequest, db: Session = Depends(get_db)):
    policy = db.scalar(select(RoutePolicy).where(RoutePolicy.subject_type == payload.subject_type, RoutePolicy.subject_id == payload.subject_id))
    if policy: policy.routes = payload.routes
    else: policy = RoutePolicy(**payload.model_dump()); db.add(policy)
    db.commit()
    return {"id": policy.id, "subject_type": policy.subject_type, "subject_id": policy.subject_id, "routes": policy.routes}


@app.delete("/v1/admin/route-policies/{policy_id}", tags=["routing"], dependencies=[Depends(require_admin)])
def delete_route_policy(policy_id: str, db: Session = Depends(get_db)):
    policy = db.get(RoutePolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Route policy not found")
    db.delete(policy)
    db.commit()
    return {"id": policy_id, "removed": True}
