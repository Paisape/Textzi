"""GST-aware proforma quotes tied to a CRM Lead -- deliberately not an IRN-registered e-invoice
(mandatory only above Rs 5 crore turnover, past this product's SME target), so this is a plain
PDF-generation + optional WhatsApp-send feature, not an Invoice Registration Portal integration.
"Convert to invoice" reuses the existing SMS-billing Invoice pipeline (invoicing.py) as-is,
including its already-working Zoho Books sync -- a quote becomes exactly the same Invoice row
type Textzi's own billing uses, not a parallel CRM invoice table.

Deliberately its own module, never importing from or importing into dispatch.py/providers.py/
webhooks.py (SMS) or waba_meta.py/waba_webhooks.py (WhatsApp's inbound pipeline) -- it does import
waba_dispatch.send_whatsapp_media for the one-directional "send this quote via WhatsApp" action,
same pattern as every other CRM-to-channel touchpoint this session (crm_campaigns, etc.)."""
import os
from datetime import datetime, timezone

from fpdf import FPDF
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .auth import require_user
from .config import settings
from .database import get_db
from .invoicing import _safe_text, create_draft_invoice, issue_invoice
from .models import Company, Contact, CrmSettings, Entity, Lead, Organization, Quote, User, WabaConnection
from .schemas import QuoteCreateRequest, QuoteOut
from .services import GST_RATE, DomainError, resolve_user_entity, state_code_from_gstin

router = APIRouter(prefix="/v1/crm/quotes", tags=["crm-quotes"])


def _resolve_entity(db: Session, user: User) -> Entity:
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _compute_totals(quote: Quote, entity_state: str | None, company_state: str | None) -> dict:
    subtotal = sum(item["quantity"] * item["unit_price"] for item in quote.line_items)
    gst = subtotal * GST_RATE
    same_state = bool(entity_state and company_state and entity_state == company_state) or not company_state
    cgst = gst / 2 if same_state else 0
    sgst = gst / 2 if same_state else 0
    igst = gst if not same_state else 0
    return {"subtotal": round(subtotal, 2), "cgst": round(cgst, 2), "sgst": round(sgst, 2), "igst": round(igst, 2), "total": round(subtotal + gst, 2)}


def _quote_out(db: Session, quote: Quote) -> QuoteOut:
    lead = db.get(Lead, quote.lead_id)
    contact = db.get(Contact, lead.contact_id) if lead else None
    company = db.get(Company, contact.company_id) if contact and contact.company_id else None
    entity = db.get(Entity, quote.entity_id)
    organization = db.get(Organization, entity.organization_id) if entity else None
    entity_state = (organization.state_code or state_code_from_gstin(organization.gstin)) if organization else None
    company_state = state_code_from_gstin(company.gstin) if company else None
    totals = _compute_totals(quote, entity_state, company_state)
    return QuoteOut(
        id=quote.id, lead_id=quote.lead_id, quote_number=quote.quote_number, line_items=quote.line_items, status=quote.status,
        subtotal=totals["subtotal"], cgst=totals["cgst"], sgst=totals["sgst"], igst=totals["igst"], total=totals["total"],
        has_pdf=bool(quote.pdf_path), approval_status=quote.approval_status, converted_invoice_id=quote.converted_invoice_id,
        created_at=quote.created_at.isoformat(), sent_at=quote.sent_at.isoformat() if quote.sent_at else None,
    )


def _render_quote_pdf(quote: Quote, lead: Lead, contact: Contact, company: Company | None, organization, totals: dict) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _safe_text(organization.name if organization else "Quote"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    if organization and organization.gstin:
        pdf.cell(0, 6, _safe_text(f"GSTIN: {organization.gstin}"), ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, _safe_text(f"Quote {quote.quote_number or '(draft)'}"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe_text(f"To: {company.name if company else (contact.name or contact.wa_id or 'Customer')}"), ln=True)
    if company and company.gstin:
        pdf.cell(0, 6, _safe_text(f"GSTIN: {company.gstin}"), ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(80, 8, "Description", border=1)
    pdf.cell(25, 8, "HSN", border=1)
    pdf.cell(25, 8, "Qty", border=1)
    pdf.cell(30, 8, "Unit Price", border=1)
    pdf.cell(30, 8, "Amount", border=1, ln=True)
    pdf.set_font("Helvetica", "", 10)
    for item in quote.line_items:
        amount = item["quantity"] * item["unit_price"]
        pdf.cell(80, 8, _safe_text(item["description"])[:40], border=1)
        pdf.cell(25, 8, _safe_text(item.get("hsn_code", "")), border=1)
        pdf.cell(25, 8, str(item["quantity"]), border=1)
        pdf.cell(30, 8, f"{item['unit_price']:.2f}", border=1)
        pdf.cell(30, 8, f"{amount:.2f}", border=1, ln=True)

    pdf.ln(4)
    pdf.cell(160, 7, "Subtotal", align="R")
    pdf.cell(30, 7, f"{totals['subtotal']:.2f}", ln=True)
    if totals["cgst"]:
        pdf.cell(160, 7, "CGST (9%)", align="R")
        pdf.cell(30, 7, f"{totals['cgst']:.2f}", ln=True)
        pdf.cell(160, 7, "SGST (9%)", align="R")
        pdf.cell(30, 7, f"{totals['sgst']:.2f}", ln=True)
    if totals["igst"]:
        pdf.cell(160, 7, "IGST (18%)", align="R")
        pdf.cell(30, 7, f"{totals['igst']:.2f}", ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(160, 8, "Total", align="R")
    pdf.cell(30, 8, f"{totals['total']:.2f}", ln=True)
    return bytes(pdf.output())


@router.get("", response_model=list[QuoteOut])
def list_quotes(lead_id: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    query = select(Quote).where(Quote.entity_id == entity.id)
    if lead_id:
        query = query.where(Quote.lead_id == lead_id)
    quotes = db.scalars(query.order_by(Quote.created_at.desc())).all()
    return [_quote_out(db, q) for q in quotes]


@router.post("", response_model=QuoteOut)
def create_quote(payload: QuoteCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    lead = db.scalar(select(Lead).where(Lead.id == payload.lead_id, Lead.entity_id == entity.id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    quote = Quote(entity_id=entity.id, lead_id=lead.id, line_items=[item.model_dump() for item in payload.line_items], created_by_user_id=user.id)
    db.add(quote)
    db.commit()
    db.refresh(quote)

    # Approval workflow -- if this quote's total exceeds CrmSettings.quote_approval_threshold,
    # it can't be sent until approved (see send_quote below).
    settings_row = db.get(CrmSettings, entity.id)
    if settings_row and settings_row.quote_approval_threshold:
        out = _quote_out(db, quote)
        if out.total > float(settings_row.quote_approval_threshold):
            quote.approval_status = "pending"
            db.commit()
            db.refresh(quote)
    return _quote_out(db, quote)


@router.delete("/{quote_id}")
def delete_quote(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    db.delete(quote)
    db.commit()
    return {"deleted": True}


@router.post("/{quote_id}/approve", response_model=QuoteOut)
def approve_quote(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.approval_status != "pending":
        raise HTTPException(status_code=409, detail="This quote isn't waiting for approval")
    quote.approval_status = "approved"
    quote.approved_by_user_id = user.id
    quote.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)


def _get_pdf_bytes(db: Session, quote: Quote) -> bytes:
    lead = db.get(Lead, quote.lead_id)
    contact = db.get(Contact, lead.contact_id)
    company = db.get(Company, contact.company_id) if contact.company_id else None
    entity = db.get(Entity, quote.entity_id)
    organization = db.get(Organization, entity.organization_id)
    entity_state = organization.state_code or state_code_from_gstin(organization.gstin)
    company_state = state_code_from_gstin(company.gstin) if company else None
    totals = _compute_totals(quote, entity_state, company_state)
    return _render_quote_pdf(quote, lead, contact, company, organization, totals)


@router.get("/{quote_id}/pdf")
def download_quote_pdf(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    pdf_bytes = _get_pdf_bytes(db, quote)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={quote.quote_number or quote.id}.pdf"})


@router.post("/{quote_id}/send-whatsapp", response_model=QuoteOut)
def send_quote_via_whatsapp(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.approval_status == "pending":
        raise HTTPException(status_code=422, detail="This quote is waiting for manager approval before it can be sent")
    lead = db.get(Lead, quote.lead_id)
    contact = db.get(Contact, lead.contact_id)
    if not contact.wa_id:
        raise HTTPException(status_code=422, detail="This contact has no WhatsApp number to send to")
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number before sending quotes")

    if not quote.quote_number:
        db.execute(text("CREATE SEQUENCE IF NOT EXISTS quote_number_seq"))
        seq_val = db.execute(text("SELECT nextval('quote_number_seq')")).scalar()
        quote.quote_number = f"QUO-{datetime.now(timezone.utc).year}-{seq_val:06d}"

    pdf_bytes = _get_pdf_bytes(db, quote)
    directory = os.path.join(settings.uploads_dir, "crm_quotes")
    os.makedirs(directory, exist_ok=True)
    local_copy_path = os.path.join(directory, f"{quote.id}.pdf")
    with open(local_copy_path, "wb") as f:
        f.write(pdf_bytes)
    quote.pdf_path = local_copy_path

    from .waba_dispatch import send_whatsapp_media
    from .waba_meta import MetaApiError
    filename = f"{quote.quote_number}.pdf"
    try:
        send_whatsapp_media(db, entity.id, contact.wa_id, pdf_bytes, filename, "application/pdf", "document", f"Quote {quote.quote_number}", sent_by_user_id=user.id)
    except (DomainError, MetaApiError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this quote: {exc}") from exc

    quote.status = "sent"
    quote.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)


@router.post("/{quote_id}/convert-to-invoice", response_model=QuoteOut)
def convert_quote_to_invoice(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Reuses the exact same Invoice pipeline SMS billing uses -- create_draft_invoice +
    issue_invoice, which already handles Zoho Books sync (if the organization is linked) with no
    extra code needed here. Tally isn't wired in (no cloud API to call -- see the plan's own note
    on this); an XML-export path for Tally is a separate, later addition."""
    entity = _resolve_entity(db, user)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.status != "accepted":
        raise HTTPException(status_code=409, detail="Only an accepted quote can be converted to an invoice")
    if quote.converted_invoice_id:
        raise HTTPException(status_code=409, detail="This quote has already been converted to an invoice")

    out = _quote_out(db, quote)
    invoice = create_draft_invoice(
        db, entity, type="crm_quote", base_amount=out.subtotal, gst_amount=round(out.cgst + out.sgst + out.igst, 2),
        reference=quote.id, notes=f"Converted from quote {quote.quote_number or quote.id}",
    )
    issue_invoice(db, invoice)
    quote.converted_invoice_id = invoice.id
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)


@router.post("/{quote_id}/status/{status}", response_model=QuoteOut)
def set_quote_status(quote_id: str, status: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if status not in ("accepted", "rejected"):
        raise HTTPException(status_code=422, detail="status must be accepted or rejected")
    entity = _resolve_entity(db, user)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    quote.status = status
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)
