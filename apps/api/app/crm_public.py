"""Unauthenticated endpoint backing the embeddable web lead-capture form (crm.py's /web-form
settings CRUD manages the config this reads; the actual <iframe> target is a frontend route that
calls these two endpoints). Same posture as public.py: no require_user anywhere in this file."""
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .crm import rescore_lead
from .crm_sequences import apply_lead_routing
from .database import get_db
from .models import CrmContact, Entity, Lead, WebForm
from .schemas import PublicWebFormOut, WebFormSubmitRequest, WebFormSubmitResponse
from .services import channel_active, log_activity
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
