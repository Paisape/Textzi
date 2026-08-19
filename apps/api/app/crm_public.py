"""Unauthenticated endpoints reachable by someone outside the org: the embeddable web
lead-capture form (crm.py's /web-form settings CRUD manages the config this reads; the actual
<iframe> target is a frontend route that calls these two endpoints), the public quote signing
link (crm_quotes.py's send_quote_via_whatsapp sends this URL alongside the PDF), and the public
meeting-booking link (crm.py's /settings/booking-link CRUD manages the config this reads).
Same posture as public.py: no require_user anywhere in this file."""
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .crm import rescore_lead
from .crm_quotes import _quote_out
from .crm_sequences import apply_lead_routing
from .database import get_db
from .models import BookingLink, BusinessHours, Company, CrmContact, Deal, Entity, Lead, Organization, Quote, Task, WebForm
from .schemas import (
    PublicBookingLinkOut, PublicBookingRequest, PublicBookingResponse, PublicBookingSlotsOut,
    PublicQuoteOut, PublicQuoteSignRequest, PublicWebFormOut, WebFormSubmitRequest, WebFormSubmitResponse,
)
from .services import channel_active, client_ip, log_activity
from .turnstile import require_turnstile

router = APIRouter(prefix="/v1/public", tags=["public"])


def _active_form(db: Session, entity_id: str) -> WebForm:
    form = db.get(WebForm, entity_id)
    if not form or not form.enabled or not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=404, detail="Form not found")
    return form


@router.get("/lead-form/{entity_id}", response_model=PublicWebFormOut)
def get_public_lead_form(entity_id: str, db: Session = Depends(get_db)):
    form = _active_form(db, entity_id)
    return PublicWebFormOut(enabled=form.enabled, fields=form.fields)


@router.post("/lead-form/{entity_id}/submit", response_model=WebFormSubmitResponse)
def submit_public_lead_form(entity_id: str, payload: WebFormSubmitRequest, request: Request, db: Session = Depends(get_db)):
    form = _active_form(db, entity_id)
    require_turnstile(payload.turnstile_token, request, db)

    # Only accept values for fields the form owner actually configured -- an attacker POSTing
    # arbitrary extra keys shouldn't be able to write anything beyond the admin-chosen field list.
    values = {k: escape(v.strip())[:2000] for k, v in payload.values.items() if k in form.fields and v.strip()}
    if not values.get("name"):
        raise HTTPException(status_code=422, detail="name is required")

    email = values.get("email") or None
    phone = values.get("phone") or None
    contact = None
    if email:
        contact = db.query(CrmContact).filter(CrmContact.entity_id == entity_id, CrmContact.email == email).first()
    if not contact and phone:
        contact = db.query(CrmContact).filter(CrmContact.entity_id == entity_id, CrmContact.phone == phone).first()

    extra_fields = {k: v for k, v in values.items() if k not in ("name", "email", "phone", "message", "company")}
    if not contact:
        # A web-form submission was never a WhatsApp conversation -- this creates a CrmContact
        # directly, no WABA Contact involved at all (matches "whatsapp have own and crm have
        # own" -- a web-form lead is CRM-native from the start).
        contact = CrmContact(
            entity_id=entity_id, name=values.get("name"), email=email, phone=phone, source="web_form",
            custom_fields=extra_fields,
        )
        db.add(contact)
        db.flush()

    lead = Lead(
        entity_id=entity_id, contact_id=contact.id, company_name=values.get("company"),
        source="web_form", notes=values.get("message"), custom_fields=extra_fields,
    )
    db.add(lead)
    db.flush()
    apply_lead_routing(db, lead, contact)
    rescore_lead(db, lead)
    entity = db.get(Entity, entity_id)
    log_activity(db, entity.organization_id, "web_form_lead_created", f"New web form lead: {values.get('name')}", request=request)
    db.commit()

    return WebFormSubmitResponse(message=form.success_message)


def _get_sendable_quote(db: Session, quote_id: str) -> Quote:
    quote = db.get(Quote, quote_id)
    if not quote or quote.status not in ("sent", "accepted", "rejected"):
        # A draft quote was never sent to this customer -- nothing to show at this link yet, and
        # a not-found response here (vs. a 403) avoids confirming the id is a real, unsent quote.
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


def _public_quote_out(db: Session, quote: Quote) -> PublicQuoteOut:
    out = _quote_out(db, quote)
    deal = db.get(Deal, quote.deal_id)
    contact = db.get(CrmContact, deal.contact_id) if deal else None
    company = db.get(Company, contact.company_id) if contact and contact.company_id else None
    return PublicQuoteOut(
        quote_number=out.quote_number, line_items=out.line_items, status=out.status,
        subtotal=out.subtotal, cgst=out.cgst, sgst=out.sgst, igst=out.igst, total=out.total,
        company_name=company.name if company else "", contact_name=contact.name if contact else "",
        signed_by_name=out.signed_by_name, signed_at=out.signed_at,
    )


@router.get("/quote/{quote_id}", response_model=PublicQuoteOut)
def get_public_quote(quote_id: str, db: Session = Depends(get_db)):
    return _public_quote_out(db, _get_sendable_quote(db, quote_id))


@router.post("/quote/{quote_id}/sign", response_model=PublicQuoteOut)
def sign_public_quote(quote_id: str, payload: PublicQuoteSignRequest, request: Request, db: Session = Depends(get_db)):
    quote = _get_sendable_quote(db, quote_id)
    require_turnstile(payload.turnstile_token, request, db)
    if quote.status != "sent":
        raise HTTPException(status_code=409, detail=f"This quote has already been {quote.status}")

    quote.status = "accepted" if payload.accept else "rejected"
    quote.signed_by_name = payload.signed_by_name.strip()
    quote.signed_at = datetime.now(timezone.utc)
    quote.signed_ip = client_ip(request)
    entity = db.get(Entity, quote.entity_id)
    log_activity(db, entity.organization_id, "quote_signed", f"Quote {quote.quote_number or quote.id} {quote.status} by {quote.signed_by_name}", request=request)
    db.commit()
    db.refresh(quote)
    return _public_quote_out(db, quote)


def _active_booking_link(db: Session, slug: str) -> BookingLink:
    link = db.scalar(select(BookingLink).where(BookingLink.slug == slug))
    if not link or not link.active or not channel_active(db, link.entity_id, "crm"):
        raise HTTPException(status_code=404, detail="Booking link not found")
    return link


@router.get("/booking/{slug}", response_model=PublicBookingLinkOut)
def get_public_booking_link(slug: str, db: Session = Depends(get_db)):
    link = _active_booking_link(db, slug)
    entity = db.get(Entity, link.entity_id)
    organization = db.get(Organization, entity.organization_id) if entity else None
    return PublicBookingLinkOut(duration_minutes=link.duration_minutes, entity_name=organization.name if organization else "")


def _day_window(hours: BusinessHours, day: date) -> tuple[time, time] | None:
    day_key = day.strftime("%a").lower()[:3]
    day_hours = hours.schedule.get(day_key)
    if not day_hours:
        return None
    try:
        return time.fromisoformat(day_hours["open"]), time.fromisoformat(day_hours["close"])
    except (KeyError, ValueError):
        return None


@router.get("/booking/{slug}/availability", response_model=PublicBookingSlotsOut)
def get_public_booking_availability(slug: str, on: str, db: Session = Depends(get_db)):
    """Open slots for one calendar date, sliced into BookingLink.duration_minutes increments from
    BusinessHours' own weekly schedule, minus any Task type="meeting" already occupying that
    window -- no separate slot-storage table, this is computed fresh on every request."""
    link = _active_booking_link(db, slug)
    hours = db.get(BusinessHours, link.entity_id)
    if not hours or not hours.enabled:
        return PublicBookingSlotsOut(date=on, slots=[])
    try:
        target_day = date.fromisoformat(on)
        tz = ZoneInfo(hours.timezone)
    except (ValueError, KeyError):
        raise HTTPException(status_code=422, detail="Invalid date or entity timezone")
    window = _day_window(hours, target_day)
    if not window:
        return PublicBookingSlotsOut(date=on, slots=[])
    open_t, close_t = window
    day_start = datetime.combine(target_day, open_t, tzinfo=tz)
    day_end = datetime.combine(target_day, close_t, tzinfo=tz)

    busy = db.scalars(
        select(Task).where(
            Task.entity_id == link.entity_id, Task.type == "meeting", Task.due_at >= day_start.astimezone(timezone.utc),
            Task.due_at < day_end.astimezone(timezone.utc),
        ),
    ).all()
    busy_windows = [(t.due_at, t.due_at + timedelta(minutes=t.duration_minutes or link.duration_minutes)) for t in busy]

    now = datetime.now(timezone.utc)
    slots: list[str] = []
    cursor = day_start
    step = timedelta(minutes=link.duration_minutes)
    while cursor + step <= day_end:
        slot_end = cursor + step
        cursor_utc = cursor.astimezone(timezone.utc)
        if cursor_utc > now and not any(cursor_utc < b_end and slot_end.astimezone(timezone.utc) > b_start for b_start, b_end in busy_windows):
            slots.append(cursor.strftime("%H:%M"))
        cursor = slot_end
    return PublicBookingSlotsOut(date=on, slots=slots)


@router.post("/booking/{slug}/book", response_model=PublicBookingResponse)
def book_public_slot(slug: str, payload: PublicBookingRequest, request: Request, db: Session = Depends(get_db)):
    link = _active_booking_link(db, slug)
    require_turnstile(payload.turnstile_token, request, db)
    if not payload.email and not payload.phone:
        raise HTTPException(status_code=422, detail="Provide an email or phone number")
    try:
        slot_start = datetime.fromisoformat(payload.slot_start)
        if slot_start.tzinfo is None:
            raise ValueError("slot_start must include a timezone offset")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    contact = None
    if payload.email:
        contact = db.scalar(select(CrmContact).where(CrmContact.entity_id == link.entity_id, CrmContact.email == payload.email))
    if not contact and payload.phone:
        contact = db.scalar(select(CrmContact).where(CrmContact.entity_id == link.entity_id, CrmContact.phone == payload.phone))
    if not contact:
        contact = CrmContact(entity_id=link.entity_id, name=payload.name.strip(), email=payload.email, phone=payload.phone, source="manual")
        db.add(contact)
        db.flush()

    # Re-check the slot is still free right before booking -- the availability list above is a
    # point-in-time read, and two visitors could otherwise both see the same open slot.
    conflict = db.scalar(
        select(Task.id).where(
            Task.entity_id == link.entity_id, Task.type == "meeting",
            Task.due_at < slot_start.astimezone(timezone.utc) + timedelta(minutes=link.duration_minutes),
            Task.due_at + timedelta(minutes=link.duration_minutes) > slot_start.astimezone(timezone.utc),
        ).limit(1),
    )
    if conflict:
        raise HTTPException(status_code=409, detail="This slot was just booked by someone else -- pick another time")

    task = Task(
        entity_id=link.entity_id, contact_id=contact.id, title=f"Meeting with {payload.name.strip()}",
        type="meeting", due_at=slot_start.astimezone(timezone.utc), duration_minutes=link.duration_minutes,
    )
    db.add(task)
    entity = db.get(Entity, link.entity_id)
    log_activity(db, entity.organization_id, "booking_link_meeting_booked", f"{payload.name.strip()} booked a meeting via the public booking link", request=request)
    db.commit()
    return PublicBookingResponse(confirmed_at=datetime.now(timezone.utc).isoformat())
