"""Reusable document templates (proposals, contracts) with {{merge_field}} placeholders, generated
against a Deal as a plain PDF -- same bounded PDF-generation scope as crm_quotes.py's quote PDF,
not a rich HTML-to-PDF document engine (no new heavy dependency for it).

Deliberately its own module, never importing from or importing into dispatch.py/providers.py/
webhooks.py (SMS) or waba_meta.py/waba_webhooks.py (WhatsApp's inbound pipeline) -- same isolation
principle as every other CRM-adjacent module."""
from datetime import datetime, timezone

from fpdf import FPDF
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .invoicing import _safe_text
from .models import Company, CrmContact, Deal, DocumentTemplate, Entity, Organization, User
from .permissions import require_channel_scope, require_page_scope_for
from .schemas import DocumentTemplateCreateRequest, DocumentTemplateOut, DocumentTemplateUpdateRequest
from .services import DomainError, channel_active, resolve_user_entity

router = APIRouter(prefix="/v1/crm/document-templates", tags=["crm-documents"], dependencies=[Depends(require_channel_scope("crm")), Depends(require_page_scope_for("channels-crm"))])


def _resolve_entity(db: Session, user: User) -> Entity:
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_crm(db: Session, entity_id: str) -> None:
    if not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to use document templates")


def _template_out(template: DocumentTemplate) -> DocumentTemplateOut:
    return DocumentTemplateOut(id=template.id, name=template.name, applies_to=template.applies_to, body=template.body, created_at=template.created_at.isoformat())


@router.get("", response_model=list[DocumentTemplateOut])
def list_templates(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    templates = db.scalars(select(DocumentTemplate).where(DocumentTemplate.entity_id == entity.id).order_by(DocumentTemplate.name)).all()
    return [_template_out(t) for t in templates]


@router.post("", response_model=DocumentTemplateOut)
def create_template(payload: DocumentTemplateCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    template = DocumentTemplate(entity_id=entity.id, name=payload.name.strip(), applies_to=payload.applies_to, body=payload.body)
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.patch("/{template_id}", response_model=DocumentTemplateOut)
def update_template(template_id: str, payload: DocumentTemplateUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    template = db.get(DocumentTemplate, template_id)
    if not template or template.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Document template not found")
    if "name" in payload.model_fields_set and payload.name:
        template.name = payload.name.strip()
    if "applies_to" in payload.model_fields_set and payload.applies_to:
        template.applies_to = payload.applies_to
    if "body" in payload.model_fields_set and payload.body:
        template.body = payload.body
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.delete("/{template_id}")
def delete_template(template_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    template = db.get(DocumentTemplate, template_id)
    if not template or template.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Document template not found")
    db.delete(template)
    db.commit()
    return {"deleted": True}


def _merge_fields(db: Session, deal: Deal) -> dict[str, str]:
    contact = db.get(CrmContact, deal.contact_id)
    company = db.get(Company, contact.company_id) if contact and contact.company_id else None
    entity = db.get(Entity, deal.entity_id)
    organization = db.get(Organization, entity.organization_id) if entity and entity.organization_id else None
    return {
        "contact.name": (contact.name if contact else None) or "",
        "contact.phone": (contact.phone if contact else None) or "",
        "contact.email": (contact.email if contact else None) or "",
        "company.name": (company.name if company else None) or "",
        "deal.name": deal.name or "",
        "deal.value": f"{float(deal.value):,.2f}" if deal.value else "",
        "deal.stage": deal.stage,
        "organization.name": (organization.name if organization else None) or "",
        "date.today": datetime.now(timezone.utc).strftime("%d %b %Y"),
    }


def _render_document_pdf(name: str, body: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, _safe_text(name), ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(4)
    for paragraph in body.split("\n\n"):
        pdf.multi_cell(0, 7, _safe_text(paragraph.strip()))
        pdf.ln(3)
    return bytes(pdf.output())


class DocumentGenerateRequest(BaseModel):
    deal_id: str


@router.post("/{template_id}/generate")
def generate_document(template_id: str, payload: DocumentGenerateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    template = db.get(DocumentTemplate, template_id)
    if not template or template.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Document template not found")
    deal = db.scalar(select(Deal).where(Deal.id == payload.deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    fields = _merge_fields(db, deal)
    body = template.body
    for key, value in fields.items():
        body = body.replace("{{" + key + "}}", value)
    pdf_bytes = _render_document_pdf(template.name, body)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{template.name}.pdf"'})
