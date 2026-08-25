"""Unauthenticated endpoints the embeddable widget script calls directly from a visitor's browser
on a third-party website, plus the widget script itself (GET /widget.js -- a plain string
constant, no build step, deliberately framework-free since it has to run inside an arbitrary
third-party page and stay tiny). Same posture as crm_public.py/public.py: no require_user
anywhere in this file. Origin-checked against WebchatWidgetSettings.allowed_origins on every call
-- this is the real security boundary, not the app's own CORSMiddleware (main.py's, scoped to
settings.web_origin -- Textzi's own dashboard -- which is a different, unrelated origin from
every customer's own website the widget actually gets embedded on). Confirmed via a real browser
(Playwright) against a live container: the plain HTTP endpoints here (unlike the WebSocket
handshake below, which browsers never subject to CORS at all) DO get a real preflight from the
browser, and main.py's CORSMiddleware answered it "Disallowed CORS origin" for anything but
web_origin -- meaning every fetch() call this widget makes from a real third-party site was
silently blocked before _check_origin below ever got a chance to run. WebchatCorsMiddleware fixes
this: it intercepts only this router's own path prefix, does the identical allowed_origins lookup
_check_origin does (same DB-backed allowlist, same fail-closed-on-unconfigured posture), and
issues its own CORS response/headers for exactly the origins that check already approves --
every other route in the app keeps going through main.py's CORSMiddleware exactly as before,
untouched."""
import logging
import mimetypes
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from . import waba_media
from .database import SessionLocal, get_db
from .geoip import lookup_geo
from .models import Contact, Conversation, ConversationMessage, CsatResponse, TicketGroup, WebchatVisit, WebchatWidgetSettings
from .schemas import PublicTurnstileConfigOut, WebchatCsatRequest, WebchatMessageRequest, WebchatMessageResponse, WebchatVisitRequest, WebchatVisitResponse
from .services import client_ip, get_platform_turnstile_settings, is_outside_business_hours, sanitize_rich_text, stamp_sla_due_at
from .turnstile import require_turnstile
from .waba_realtime import message_payload, publish_event
from .webchat_widget_js import WIDGET_JS

logger = logging.getLogger("textzi.webchat")

router = APIRouter(prefix="/v1/public/webchat", tags=["webchat"])

_PUBLIC_PREFIX = "/v1/public/webchat/"


_ORIGIN_AGNOSTIC_PATHS = {"/v1/public/webchat/widget.js", "/v1/public/webchat/turnstile-config"}


def _origin_allowed_for_path(db: Session, path: str, origin: str | None) -> bool:
    """Same allowlist _check_origin enforces inside the route handlers -- kept as its own tiny
    function (not a call into _check_origin, which needs a WebchatWidgetSettings row + raises
    HTTPException) since the middleware runs before routing and only needs a yes/no answer to
    decide the CORS headers, not to actually reject the request (that's still _check_origin's job,
    inside the handler, for the real 403). GET /widget.js and GET /turnstile-config have no
    widget_key in their path and are meant to be reachable by any site regardless -- neither
    carries a secret (the widget script is public by nature; the Turnstile site key is designed to
    be shipped to every visitor's browser, same reasoning as public.py's own turnstile-config
    route) -- so both are excluded from the per-widget-key origin check entirely."""
    if path in _ORIGIN_AGNOSTIC_PATHS:
        return True
    if not origin:
        return False
    parts = path[len(_PUBLIC_PREFIX):].split("/", 1)
    widget_key = parts[0] if parts else None
    if not widget_key:
        return False
    settings_row = db.scalar(select(WebchatWidgetSettings).where(WebchatWidgetSettings.widget_key == widget_key))
    return bool(settings_row and settings_row.allowed_origins and origin in settings_row.allowed_origins)


class WebchatCorsMiddleware(BaseHTTPMiddleware):
    """Registered in main.py ahead of (i.e. wrapping outside) the app's own CORSMiddleware, so it
    sees the request first for this one path prefix. Passes every other path straight through
    untouched. Owns its own short-lived DB session per request (matches the shape of every other
    place in this codebase that needs a session outside the normal Depends(get_db) request scope,
    e.g. catalog_sync.sync_all_catalogs)."""
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(_PUBLIC_PREFIX):
            return await call_next(request)

        origin = request.headers.get("origin")
        db = SessionLocal()
        try:
            allowed = _origin_allowed_for_path(db, request.url.path, origin)
        finally:
            db.close()

        if request.method == "OPTIONS":
            if not allowed:
                return Response(status_code=400, content="Disallowed CORS origin")
            return Response(status_code=200, headers={
                "Access-Control-Allow-Origin": origin or "*",
                "Access-Control-Allow-Methods": "GET, POST, PATCH",
                "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            })

        response = await call_next(request)
        if allowed and origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response


@router.get("/widget.js")
def get_widget_script():
    return Response(content=WIDGET_JS, media_type="application/javascript")


@router.get("/turnstile-config", response_model=PublicTurnstileConfigOut)
def get_widget_turnstile_config(db: Session = Depends(get_db)):
    """A webchat-scoped mirror of public.py's own /v1/public/turnstile-config -- needed because
    that route isn't covered by WebchatCorsMiddleware (which only intercepts this router's own
    path prefix), so a fetch() call to it from a real third-party embed site hits the exact same
    CORS wall this whole module exists to work around. Same site-key-isn't-a-secret reasoning as
    the original route; this one just lives somewhere the widget can actually reach it from."""
    site_key, _ = get_platform_turnstile_settings(db)
    return PublicTurnstileConfigOut(site_key=site_key)


def _widget_settings(db: Session, widget_key: str) -> WebchatWidgetSettings:
    settings_row = db.scalar(select(WebchatWidgetSettings).where(WebchatWidgetSettings.widget_key == widget_key))
    if not settings_row or not settings_row.enabled:
        raise HTTPException(status_code=404, detail="Widget not found")
    return settings_row


def _check_origin(request: Request, settings_row: WebchatWidgetSettings) -> None:
    # allowed_origins empty means "not configured yet" -- fail closed, not open, so a widget
    # can't be embedded anywhere until the customer explicitly allowlists at least one domain.
    origin = request.headers.get("origin")
    if not settings_row.allowed_origins or origin not in settings_row.allowed_origins:
        raise HTTPException(status_code=403, detail="This domain is not allowed to embed this widget")


@router.post("/{widget_key}/visit", response_model=WebchatVisitResponse)
def record_visit(widget_key: str, payload: WebchatVisitRequest, request: Request, db: Session = Depends(get_db)):
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)

    now = datetime.now(timezone.utc)
    visit = db.scalar(select(WebchatVisit).where(WebchatVisit.entity_id == settings_row.entity_id, WebchatVisit.visitor_id == payload.visitor_id))
    if not visit:
        ip = client_ip(request)
        country, city = lookup_geo(ip) if ip else (None, None)
        visit = WebchatVisit(
            entity_id=settings_row.entity_id, visitor_id=payload.visitor_id, current_url=payload.current_url,
            referrer=payload.referrer, user_agent=request.headers.get("user-agent"), ip_address=ip,
            country=country, city=city, pages_viewed=[{"url": payload.current_url, "viewed_at": now.isoformat()}],
        )
        db.add(visit)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            visit = db.scalar(select(WebchatVisit).where(WebchatVisit.entity_id == settings_row.entity_id, WebchatVisit.visitor_id == payload.visitor_id))
            if not visit:
                raise
    else:
        visit.current_url = payload.current_url
        visit.last_seen_at = now
        pages = list(visit.pages_viewed or [])
        if not pages or pages[-1].get("url") != payload.current_url:
            pages.append({"url": payload.current_url, "viewed_at": now.isoformat()})
        visit.pages_viewed = pages
    db.commit()

    offline = is_outside_business_hours(db, settings_row.entity_id, now)
    return WebchatVisitResponse(
        greeting_message=settings_row.greeting_message, bubble_color=settings_row.bubble_color,
        is_online=not offline, offline_message=settings_row.offline_message,
        proactive_trigger_enabled=settings_row.proactive_trigger_enabled,
        proactive_trigger_type=settings_row.proactive_trigger_type,
        proactive_trigger_delay_seconds=settings_row.proactive_trigger_delay_seconds,
        proactive_trigger_message=settings_row.proactive_trigger_message,
        proactive_url_pattern=settings_row.proactive_url_pattern,
    )


def _find_or_create_webchat_contact(db: Session, entity_id: str, visitor_id: str, name: str | None, email: str | None) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.visitor_id == visitor_id))
    if contact:
        if name and not contact.name:
            contact.name = name
        if email and not contact.email:
            contact.email = email
        return contact
    contact = Contact(entity_id=entity_id, visitor_id=visitor_id, name=name, email=email)
    db.add(contact)
    # Same race as every other find-or-create in this codebase (crm.py's _resolve_or_create_contact,
    # crm_email.py's _find_or_create_contact) -- two rapid messages from the same brand-new visitor
    # (e.g. a double-click on send) can both pass the SELECT above before either commits. Two
    # separate unique constraints can trigger this flush's IntegrityError here, not just one:
    # uq_contacts_entity_visitor_id (a second message from the same never-before-seen visitor_id),
    # or uq_contacts_entity_email (this offline-form submission's email already belongs to a
    # DIFFERENT existing Contact -- a returning visitor on a new device/browser, or the same
    # person's second visitor_id). Re-querying by visitor_id alone misses the second case entirely
    # -- when email collided instead, that lookup finds nothing and the original error re-raises
    # unhandled. Falling back to an email lookup when the visitor_id one comes up empty covers both.
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.visitor_id == visitor_id))
        if not contact and email:
            contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.email == email))
        if not contact:
            raise
    return contact


def _pick_least_loaded_group_member(db: Session, entity_id: str, group_id: str) -> str | None:
    """Load-balanced routing (WebchatWidgetSettings.auto_assign_enabled): whichever member of the
    default group currently has the fewest OPEN webchat conversations gets the new one. Chosen
    over a round-robin counter deliberately -- a counter has no way to account for an agent going
    offline, being removed from the group, or one agent's conversations just taking longer to
    close, so it drifts toward unfair load over time; counting current open conversations
    self-corrects on every single assignment instead."""
    group = db.get(TicketGroup, group_id)
    if not group or not group.member_user_ids:
        return None
    counts = {
        user_id: db.scalar(
            select(func.count()).select_from(Conversation).where(
                Conversation.entity_id == entity_id, Conversation.channel == "webchat",
                Conversation.assigned_user_id == user_id, Conversation.status != "resolved",
            ),
        ) or 0
        for user_id in group.member_user_ids
    }
    return min(counts, key=counts.get)


def _find_or_create_webchat_conversation(db: Session, entity_id: str, contact_id: str, default_group_id: str | None = None, auto_assign_enabled: bool = False) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact_id, Conversation.channel == "webchat"),
    )
    if conversation:
        return conversation
    # Freshdesk-style routing -- only applied at creation time, never overwrites a group/assignee
    # an agent has since reassigned on an existing conversation.
    assigned_user_id = _pick_least_loaded_group_member(db, entity_id, default_group_id) if auto_assign_enabled and default_group_id else None
    conversation = Conversation(entity_id=entity_id, contact_id=contact_id, channel="webchat", group_id=default_group_id, assigned_user_id=assigned_user_id)
    db.add(conversation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        conversation = db.scalar(
            select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact_id, Conversation.channel == "webchat"),
        )
        if not conversation:
            raise
    return conversation


@router.post("/{widget_key}/message", response_model=WebchatMessageResponse)
def send_visitor_message(widget_key: str, payload: WebchatMessageRequest, request: Request, db: Session = Depends(get_db)):
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)
    require_turnstile(payload.turnstile_token, request, db)

    contact = _find_or_create_webchat_contact(db, settings_row.entity_id, payload.visitor_id, payload.name, payload.email)
    conversation = _find_or_create_webchat_conversation(db, settings_row.entity_id, contact.id, settings_row.default_group_id, settings_row.auto_assign_enabled)

    now = datetime.now(timezone.utc)
    # sanitize_rich_text -- this body came straight from an anonymous visitor's own browser, never
    # trusted as-is (unlike an agent's own composer output elsewhere in this codebase); strips
    # everything except a small safe inline-formatting tag set before it's ever stored or rendered
    # with v-html in the agent's inbox.
    body = sanitize_rich_text(payload.body)
    message = ConversationMessage(conversation_id=conversation.id, direction="inbound", message_type="text", body=body, status="received")
    db.add(message)
    conversation.status = "open"
    conversation.last_message_at = now
    stamp_sla_due_at(db, settings_row.entity_id, conversation, now)

    visit = db.scalar(select(WebchatVisit).where(WebchatVisit.entity_id == settings_row.entity_id, WebchatVisit.visitor_id == payload.visitor_id))
    if visit:
        visit.contact_id = contact.id
        visit.conversation_id = conversation.id

    db.commit()
    db.refresh(message)
    publish_event(settings_row.entity_id, {"type": "message", "message": message_payload(message)})
    return WebchatMessageResponse(conversation_id=conversation.id, message_id=message.id)


@router.post("/{widget_key}/media", response_model=WebchatMessageResponse)
async def send_visitor_media(
    widget_key: str, request: Request, visitor_id: str = Form(...), file: UploadFile = File(...),
    name: str | None = Form(default=None), email: str | None = Form(default=None), db: Session = Depends(get_db),
):
    """Visitor-side file/image upload -- same find-or-create Contact/Conversation shape as
    send_visitor_message, reusing waba_media's own type allowlist/size caps and storage (it
    already doesn't care whether the bytes came from Meta, an agent, or here)."""
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)

    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0]
    message_type = waba_media.message_type_for_mime(mime_type or "")
    if not message_type:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{mime_type}'")
    content = await file.read()
    try:
        stored_path = waba_media.save_media(settings_row.entity_id, content, mime_type, message_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    contact = _find_or_create_webchat_contact(db, settings_row.entity_id, visitor_id, name, email)
    conversation = _find_or_create_webchat_conversation(db, settings_row.entity_id, contact.id, settings_row.default_group_id, settings_row.auto_assign_enabled)

    now = datetime.now(timezone.utc)
    message = ConversationMessage(conversation_id=conversation.id, direction="inbound", message_type=message_type, media_url=stored_path, status="received")
    db.add(message)
    conversation.status = "open"
    conversation.last_message_at = now
    stamp_sla_due_at(db, settings_row.entity_id, conversation, now)

    visit = db.scalar(select(WebchatVisit).where(WebchatVisit.entity_id == settings_row.entity_id, WebchatVisit.visitor_id == visitor_id))
    if visit:
        visit.contact_id = contact.id
        visit.conversation_id = conversation.id

    db.commit()
    db.refresh(message)
    publish_event(settings_row.entity_id, {"type": "message", "message": message_payload(message)})
    return WebchatMessageResponse(conversation_id=conversation.id, message_id=message.id)


@router.get("/{widget_key}/media/{message_id}")
def get_visitor_media(widget_key: str, message_id: str, request: Request, db: Session = Depends(get_db)):
    """Serves a webchat attachment back to the visitor's browser (their own upload, or an agent's
    reply) -- no Textzi auth exists for a visitor, so this is gated by widget_key + Origin instead
    of the token-query-param scheme /v1/waba/media/{message_id} uses for the agent side. An <img>
    tag can't attach the Origin header itself, but the browser sends it anyway on any cross-origin
    request including a plain <img src>, so the same manual check still applies here."""
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)
    message = db.get(ConversationMessage, message_id)
    if not message or not message.media_url:
        raise HTTPException(status_code=404, detail="Media not found")
    conversation = db.get(Conversation, message.conversation_id)
    if not conversation or conversation.entity_id != settings_row.entity_id or conversation.channel != "webchat":
        raise HTTPException(status_code=404, detail="Media not found")
    try:
        content = waba_media.read_media(message.media_url)
    except OSError:
        raise HTTPException(status_code=404, detail="Media file is no longer available")
    mime_type = mimetypes.guess_type(message.media_url)[0] or "application/octet-stream"
    return Response(content=content, media_type=mime_type)


@router.post("/{widget_key}/csat")
def submit_csat(widget_key: str, payload: WebchatCsatRequest, request: Request, db: Session = Depends(get_db)):
    """The widget's own inline 1-5 rating UI submits here once the visitor answers -- fills in
    the newest unanswered CsatResponse row for this visitor's conversation, same "newest
    unanswered row wins" matching logic waba_webhooks._match_csat_response already uses for the
    WhatsApp side, just reached over HTTP instead of an inbound Meta webhook."""
    settings_row = _widget_settings(db, widget_key)
    _check_origin(request, settings_row)

    contact = db.scalar(select(Contact).where(Contact.entity_id == settings_row.entity_id, Contact.visitor_id == payload.visitor_id))
    if not contact:
        raise HTTPException(status_code=404, detail="Unknown visitor")
    conversation = db.scalar(select(Conversation).where(Conversation.entity_id == settings_row.entity_id, Conversation.contact_id == contact.id, Conversation.channel == "webchat"))
    if not conversation:
        raise HTTPException(status_code=404, detail="No conversation for this visitor")
    response_row = db.scalar(
        select(CsatResponse).where(CsatResponse.conversation_id == conversation.id, CsatResponse.rating.is_(None))
        .order_by(CsatResponse.requested_at.desc()).limit(1),
    )
    if not response_row:
        raise HTTPException(status_code=404, detail="No pending rating request for this conversation")
    response_row.rating = payload.rating
    response_row.responded_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok"}
