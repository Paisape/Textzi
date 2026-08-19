"""Unauthenticated endpoints reachable by someone outside the org: the embeddable web
lead-capture form (crm.py's /web-form settings CRUD manages the config this reads; the actual
<iframe> target is a frontend route that calls these two endpoints), and the public quote
signing link (crm_quotes.py's send_quote_via_whatsapp sends this URL alongside the PDF).
Same posture as public.py: no require_user anywhere in this file."""
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .crm import rescore_lead
from .crm_quotes import _quote_out
from .crm_sequences import apply_lead_routing
from .database import get_db
from .models import Company, CrmContact, Deal, Entity, Lead, Quote, WebForm
from .schemas import PublicQuoteOut, PublicQuoteSignRequest, PublicWebFormOut, WebFormSubmitRequest, WebFormSubmitResponse
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
