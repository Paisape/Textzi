import hmac
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .admin import router as admin_router, require_admin
from .auth import router as auth_router
from .channels import router as channels_router
from .database import Base, engine, get_db
from .dispatch import dispatch_message as run_dispatch
from .invoices import router as invoices_router
from .models import ApiLog, Entity, Message, RoutePolicy, User
from .onboarding import router as onboarding_router
from .payments import router as payments_router
from .platform_admin import router as platform_admin_router
from .provider_routes import router as provider_routes_router
from .public import router as public_router
from .reports import router as reports_router
from .sms import router as sms_router
from .team import router as team_router
from .testimonials import router as testimonials_router
from .two_factor import router as two_factor_router
from .wallet import router as wallet_router
from .webhooks import router as webhooks_router
from .schemas import ApiSmsSendRequest, BulkSmsRecipientResult, BulkSmsSendRequest, BulkSmsSendResponse, RoutePolicyRequest, SmsSendResponse
from .security import encrypt_secret
from .services import (
    AuthenticationError, AuthorizationError, DomainError, RateLimitError, assert_not_opted_out, available_balance, client_ip,
    debit_wallet, enforce_rate_limit, is_encryption_enabled, mask_mobile, require_channel_active, resolve_entity_from_key,
    resolve_routes, resolve_template_by_dlt_id, sms_segment_credits,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)  # Deployment uses Alembic migrations.
    yield


app = FastAPI(title="Textzi API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(channels_router)
app.include_router(invoices_router)
app.include_router(onboarding_router)
app.include_router(payments_router)
app.include_router(platform_admin_router)
app.include_router(provider_routes_router)
app.include_router(public_router)
app.include_router(reports_router)
app.include_router(sms_router)
app.include_router(team_router)
app.include_router(testimonials_router)
app.include_router(two_factor_router)
app.include_router(wallet_router)
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
    policy by guessing/knowing another org's user id. Only honor it when the referenced user
    actually belongs to the calling entity's own organization; there's no equivalent check
    possible for X-User-Group (no Group model/ownership concept exists anywhere in the schema),
    so that header is accepted for logging only and never reaches resolve_routes."""
    if not x_user_id:
        return None
    candidate = db.get(User, x_user_id)
    if candidate and candidate.organization_id == entity.organization_id:
        return x_user_id
    return None


@app.post("/v1/sms/send", response_model=SmsSendResponse, tags=["sms"])
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
        enforce_rate_limit(f"ratelimit:sms:{entity.id}", settings.sms_rate_limit_max_requests, settings.sms_rate_limit_window_seconds)
        require_channel_active(db, entity.id, "sms")
        if idempotency_key:
            existing = db.scalar(select(Message).where(Message.entity_id == entity.id, Message.idempotency_key == idempotency_key))
            if existing:
                message_id = existing.id
                return SmsSendResponse(status=existing.status, message_id=existing.id, route=existing.route or "default", balance=available_balance(db, entity.id), credits_charged=existing.credits_charged)
        assert_not_opted_out(db, entity.id, payload.mobile)
        # No render_template call here -- the caller sends the complete, already-composed
        # message (payload.message) exactly as it should go out. resolve_template_by_dlt_id
        # still verifies it's one of this entity's own approved templates and resolves the
        # header/PE_ID/route mapping registered for it.
        template = resolve_template_by_dlt_id(db, entity.id, payload.template_id)
        route_plan = resolve_routes(db, _same_org_user_id(db, entity, x_user_id), None)
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
        status_code, error_detail = 409, "Duplicate idempotency key"
        db.rollback(); message_id = None; raise HTTPException(status_code=409, detail="Duplicate idempotency key") from exc
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
        # Costs len(recipients) units, not 1 -- otherwise a 100-recipient batch would only cost
        # as much rate-limit budget as a single send, letting bulk push up to
        # max_requests * 100 actual messages through the same window a single-send caller is
        # limited to max_requests for.
        enforce_rate_limit(f"ratelimit:sms:{entity.id}", settings.sms_rate_limit_max_requests, settings.sms_rate_limit_window_seconds, amount=len(payload.recipients))
        require_channel_active(db, entity.id, "sms")
        template = resolve_template_by_dlt_id(db, entity.id, payload.template_id)
        route_plan = resolve_routes(db, _same_org_user_id(db, entity, x_user_id), None)
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
    policies = db.scalars(select(RoutePolicy).where(RoutePolicy.active == True)).all()  # noqa: E712
    return [{"id": p.id, "subject_type": p.subject_type, "subject_id": p.subject_id, "routes": p.routes} for p in policies]


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
